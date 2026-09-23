// proxy/proxy.go
//
// 带 failover 的反向代理。
//
// 核心能力：**上游挂了自动切下一个**。
// 触发条件（三者都发生在响应体开始发送之前）：
//   - 连接被拒 / DNS 失败 / 超时
//   - 上游返回 429（限流）
//   - 上游返回 5xx（服务端错误）
//
// 实现要点（踩过的坑）：
//   Go 的 httputil.ReverseProxy **在没有缓冲时会先把响应头写给客户端**，
//   之后再调用 ModifyResponse。等我们发现有 5xx 想改道时，客户端已经
//   收到 200 状态码了 —— 改道就来不及了。
//   所以这里用一个带大小上限的 responseRecorder 把响应缓冲住，
//   只有确认是成功响应才真正写给客户端。
//
// SSE 兼容性：
//   流式响应一旦开始，就不会再 failover（也没法 failover —— 数据已经半途）。
//   缓冲上限（默认 256KB）同时起到"SSE 一开始发数据就退出缓冲模式"的作用，
//   保证长连接不会被内存吃光。
package proxy

import (
	"bytes"
	"context"
	"fmt"
	"log"
	"net/http"
	"net/http/httputil"
	"net/url"
	"sort"
	"strings"
	"sync"
	"time"
)

// 默认缓冲上限：超过这个大小就停止缓冲，直接透传（保护内存 + 让 SSE 尽早开始流）
const defaultBufferLimit = 256 * 1024

// 上游"可重试"的标记头名 —— 只在网关内部使用，不会发给客户端
const retryMarkerHeader = "X-Retryable-Upstream"

// Upstream 一个上游目标
type Upstream struct {
	Name     string `json:"name"`
	URL      string `json:"url"`
	Priority int    `json:"priority"` // 越小越先试
	Enabled  *bool  `json:"enabled"`  // nil 视为启用
}

func (u Upstream) isEnabled() bool {
	return u.Enabled == nil || *u.Enabled
}

// Config 代理配置
type Config struct {
	// 上游列表。按 Priority 升序尝试，第一个成功的胜出。
	Upstreams []Upstream `json:"upstreams"`
	// 单个上游的响应超时（秒）。0 表示不限制（对 SSE 必须不限制）
	TimeoutSeconds int `json:"timeout_seconds"`
	// 缓冲上限（字节）
	BufferLimit int `json:"buffer_limit"`
}

// retryableError 标记"这个上游不可用，应该换下一个"
type retryableError struct {
	StatusCode int
	Upstream   string
	Err        error
}

func (e *retryableError) Error() string {
	if e.Err != nil {
		return fmt.Sprintf("上游 %s 不可用：%v", e.Upstream, e.Err)
	}
	return fmt.Sprintf("上游 %s 返回 %d", e.Upstream, e.StatusCode)
}

// responseRecorder 带大小上限的响应缓冲
//
// 为什么要上限：SSE 长连接可能持续几小时、数据无限，
// 不加限制地缓冲会把网关内存吃光。
type responseRecorder struct {
	real http.ResponseWriter   // 底层 writer
	hdr  http.Header           // 私有的头缓冲 —— **不能直接用 real.Header()**
	body bytes.Buffer
	statusCode  int
	limit       int
	passthrough bool // 超过上限后置为 true，此后直接写底层
}

func newResponseRecorder(w http.ResponseWriter, limit int) *responseRecorder {
	return &responseRecorder{
		real:       w,
		hdr:        make(http.Header),
		statusCode: http.StatusOK,
		limit:      limit,
	}
}

// Header 必须返回**私有**的头 map
//
// ⚠️ 这是个踩过的坑：如果直接返回 real.Header()，那么失败上游设置的响应头
//    会留在共享的 map 里；换下一个上游重试时，客户端会看到**失败上游的头**。
//    测试里表现为：日志说「已切换到 backup」，但 X-Served-By 还是 primary。
//    Go 标准库的 httptest.ResponseRecorder 正是为此才自带一个私有 Header。
func (r *responseRecorder) Header() http.Header {
	if r.passthrough {
		return r.real.Header()
	}
	return r.hdr
}

func (r *responseRecorder) WriteHeader(code int) {
	if r.passthrough {
		r.real.WriteHeader(code)
		return
	}
	// 缓冲模式：**不立即写头**。
	// 这是 failover 能工作的关键 —— 得先看看状态码是不是 5xx，
	// 是的话就换下一个上游，不能让客户端先收到一个 200。
	r.statusCode = code
}

func (r *responseRecorder) Write(b []byte) (int, error) {
	if r.passthrough {
		return r.real.Write(b)
	}
	if r.body.Len()+len(b) > r.limit {
		// 超限：先把已缓冲的部分倒出去，之后转为直通
		// 这一步之后就不再 failover 了（数据已经发给客户端）
		r.WriteHeaderNow()
		if r.body.Len() > 0 {
			if _, err := r.real.Write(r.body.Bytes()); err != nil {
				return 0, err
			}
			r.body.Reset()
		}
		return r.real.Write(b)
	}
	return r.body.Write(b)
}

// WriteHeaderNow 把缓冲的响应头与状态码真正写给客户端
// 仅在确认响应可用之后调用
func (r *responseRecorder) WriteHeaderNow() {
	if r.passthrough {
		return
	}
	r.passthrough = true
	dst := r.real.Header()
	for k := range dst { // 清掉可能残留的头
		delete(dst, k)
	}
	for k, vs := range r.hdr {
		for _, v := range vs {
			dst.Add(k, v)
		}
	}
	r.real.WriteHeader(r.statusCode)
}

// New 创建带 failover 的反向代理 handler
//
// 兼容旧用法：只传一个 targetURL 时行为与单上游相同。
func New(cfg Config) (http.HandlerFunc, error) {
	ups := make([]Upstream, 0, len(cfg.Upstreams))
	for _, u := range cfg.Upstreams {
		if u.isEnabled() {
			ups = append(ups, u)
		}
	}
	if len(ups) == 0 {
		return nil, fmt.Errorf("没有可用的上游（检查 upstreams 配置）")
	}
	// 按优先级排序：数字越小越先试
	sort.SliceStable(ups, func(i, j int) bool { return ups[i].Priority < ups[j].Priority })

	limit := cfg.BufferLimit
	if limit <= 0 {
		limit = defaultBufferLimit
	}

	var timeout time.Duration
	if cfg.TimeoutSeconds > 0 {
		timeout = time.Duration(cfg.TimeoutSeconds) * time.Second
	}

	proxies := make([]*httputil.ReverseProxy, 0, len(ups))
	for _, u := range ups {
		p, err := buildProxy(u, timeout)
		if err != nil {
			return nil, err
		}
		proxies = append(proxies, p)
	}

	names := make([]string, len(ups))
	for i, u := range ups {
		names[i] = u.Name
	}
	log.Printf("代理已就绪，上游顺序：%s", strings.Join(names, " → "))

	return func(w http.ResponseWriter, r *http.Request) {
		var lastErr error

		for i, p := range proxies {
			rec := newResponseRecorder(w, limit)
			p.ServeHTTP(rec, r)

			// 上游标记的"可重试"信号。
			// ⚠️ 必须从 rec 读，不能从 w 读 —— 缓冲模式下所有头都写在
			//    rec 的私有 map 里，还没提交给客户端。
			if mark := rec.Header().Get(retryMarkerHeader); mark != "" {
				rec.Header().Del(retryMarkerHeader)
				lastErr = &retryableError{StatusCode: rec.statusCode, Upstream: ups[i].Name}
				log.Printf("[failover] %s 不可用（%s），尝试下一个", ups[i].Name, mark)
				continue
			}

			// 成功 —— 先把状态码与响应头写出去，再写缓冲的响应体
			rec.WriteHeaderNow()
			if rec.body.Len() > 0 {
				if _, err := w.Write(rec.body.Bytes()); err != nil {
					log.Printf("写响应失败：%v", err)
				}
			}
			if i > 0 {
				log.Printf("[failover] 请求最终由 %s 处理", ups[i].Name)
			}
			return
		}

		// 全部上游都挂了 —— 如实返回，不假装成功
		log.Printf("[failover] 全部上游不可用：%v", lastErr)
		w.Header().Set("Content-Type", "application/json; charset=utf-8")
		w.WriteHeader(http.StatusServiceUnavailable)
		fmt.Fprintf(w, `{"error":"all upstreams unavailable","detail":%q}`, lastErr.Error())
	}, nil
}

// buildProxy 为单个上游构建 ReverseProxy
func buildProxy(u Upstream, timeout time.Duration) (*httputil.ReverseProxy, error) {
	target, err := url.Parse(u.URL)
	if err != nil {
		return nil, fmt.Errorf("上游 %s 的 URL 非法：%w", u.Name, err)
	}

	rp := httputil.NewSingleHostReverseProxy(target)
	originalDirector := rp.Director
	rp.Director = func(req *http.Request) {
		originalDirector(req)
		req.Host = target.Host
	}

	// SSE 不能缓冲
	rp.FlushInterval = -1

	if timeout > 0 {
		rp.Transport = &http.Transport{
			ResponseHeaderTimeout: timeout,
		}
	}

	// 判断这个上游的响应是否"不可用，应该换下一个"
	rp.ModifyResponse = func(resp *http.Response) error {
		if resp.StatusCode == http.StatusTooManyRequests || resp.StatusCode >= 500 {
			// 通知外层：这次不算数
			resp.Header.Set(retryMarkerHeader, fmt.Sprintf("HTTP %d", resp.StatusCode))
		}
		return nil
	}

	// 连接层错误（拒绝、DNS、超时）→ 标记为可重试
	rp.ErrorHandler = func(w http.ResponseWriter, r *http.Request, err error) {
		if isContextCanceled(err) {
			return // 客户端主动断开，不是上游的问题
		}
		w.Header().Set(retryMarkerHeader, err.Error())
		w.WriteHeader(http.StatusBadGateway)
		_, _ = w.Write([]byte(err.Error()))
	}

	return rp, nil
}

func isContextCanceled(err error) bool {
	if err == nil {
		return false
	}
	return err == context.Canceled ||
		strings.Contains(err.Error(), "context canceled") ||
		strings.Contains(err.Error(), "client disconnected")
}

// ─────────────────────────────────────────────────────────────
// 全局配置热更新（阶段三扩展点：将来可以从配置中心动态改上游）
// ─────────────────────────────────────────────────────────────

var (
	currentHandler http.HandlerFunc
	handlerMu      sync.RWMutex
)

// SetHandler 由 main 在启动时注入；后续可实现热更新
func SetHandler(h http.HandlerFunc) {
	handlerMu.Lock()
	defer handlerMu.Unlock()
	currentHandler = h
}

// Handler 返回当前生效的 handler
func Handler() http.HandlerFunc {
	handlerMu.RLock()
	defer handlerMu.RUnlock()
	return currentHandler
}
