// proxy/proxy_test.go
//
// failover 行为测试。
//
// 这是阶段三 P0 3.2 的验收依据：
//   「模拟上游返回 429，请求自动切换到备用上游且调用方无感」
//
// 用 httptest 起真实的 HTTP 上游，不是打桩 —— 测的是真实的连接与重试路径。
package proxy

import (
	"fmt"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

// newUpstream 起一个测试上游，行为由 status 决定；返回它的名字与关闭函数
func newUpstream(t *testing.T, name string, status int) (*httptest.Server, string) {
	t.Helper()
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("X-Served-By", name)
		if status >= 400 {
			w.WriteHeader(status)
			fmt.Fprintf(w, `{"error":"upstream %s failed with %d"}`, name, status)
			return
		}
		w.WriteHeader(status)
		fmt.Fprintf(w, `{"ok":true,"upstream":%q}`, name)
	}))
	t.Cleanup(srv.Close)
	return srv, name
}

// newGateway 用给定的上游建一个网关 handler
func newGateway(t *testing.T, ups ...Upstream) http.HandlerFunc {
	t.Helper()
	h, err := New(Config{Upstreams: ups, BufferLimit: 1 << 20})
	if err != nil {
		t.Fatalf("创建代理失败：%v", err)
	}
	return h
}

func doGet(t *testing.T, h http.HandlerFunc, path string) *http.Response {
	t.Helper()
	rec := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, path, nil)
	h(rec, req)
	return rec.Result()
}

func TestPrimaryHealthy(t *testing.T) {
	s1, n1 := newUpstream(t, "primary", 200)
	s2, _ := newUpstream(t, "backup", 200)

	h := newGateway(t,
		Upstream{Name: "primary", URL: s1.URL, Priority: 0},
		Upstream{Name: "backup", URL: s2.URL, Priority: 1},
	)

	resp := doGet(t, h, "/health")
	if resp.StatusCode != 200 {
		t.Fatalf("期望 200，实际 %d", resp.StatusCode)
	}
	if got := resp.Header.Get("X-Served-By"); got != n1 {
		t.Errorf("主上游健康时应由 primary 处理，实际 %q", got)
	}
}

// 阶段三 P0 3.2 的核心验收：主上游 503 → 自动切备用，且调用方无感
func TestFailoverOn503(t *testing.T) {
	s1, _ := newUpstream(t, "primary", http.StatusServiceUnavailable)
	s2, n2 := newUpstream(t, "backup", 200)

	h := newGateway(t,
		Upstream{Name: "primary", URL: s1.URL, Priority: 0},
		Upstream{Name: "backup", URL: s2.URL, Priority: 1},
	)

	resp := doGet(t, h, "/chat")
	if resp.StatusCode != 200 {
		t.Fatalf("主上游 503 后应自动切换并返回 200，实际 %d", resp.StatusCode)
	}
	if got := resp.Header.Get("X-Served-By"); got != n2 {
		t.Errorf("应由 backup 处理，实际 %q", got)
	}
}

func TestFailoverOn429(t *testing.T) {
	s1, _ := newUpstream(t, "primary", http.StatusTooManyRequests)
	s2, n2 := newUpstream(t, "backup", 200)

	h := newGateway(t,
		Upstream{Name: "primary", URL: s1.URL, Priority: 0},
		Upstream{Name: "backup", URL: s2.URL, Priority: 1},
	)

	resp := doGet(t, h, "/chat")
	if resp.StatusCode != 200 {
		t.Fatalf("主上游 429 后应自动切换，实际 %d", resp.StatusCode)
	}
	if got := resp.Header.Get("X-Served-By"); got != n2 {
		t.Errorf("应由 backup 处理，实际 %q", got)
	}
}

// 上游端口没人监听 —— 连接被拒，也应 failover
func TestFailoverOnConnectionRefused(t *testing.T) {
	// 起一个 server 再关掉，拿到一个"确定没人监听"的地址
	dead := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {}))
	deadURL := dead.URL
	dead.Close()

	s2, n2 := newUpstream(t, "backup", 200)

	h := newGateway(t,
		Upstream{Name: "dead", URL: deadURL, Priority: 0},
		Upstream{Name: "backup", URL: s2.URL, Priority: 1},
	)

	resp := doGet(t, h, "/chat")
	if resp.StatusCode != 200 {
		t.Fatalf("连接被拒后应 failover，实际 %d", resp.StatusCode)
	}
	if got := resp.Header.Get("X-Served-By"); got != n2 {
		t.Errorf("应由 backup 处理，实际 %q", got)
	}
}

// 优先级顺序：应该按 priority 升序尝试，而不是配置里的书写顺序
func TestPriorityOrderWins(t *testing.T) {
	slow, _ := newUpstream(t, "priority-9", 200)
	fast, nFast := newUpstream(t, "priority-0", 200)

	// 故意把 priority 大的写在前面
	h := newGateway(t,
		Upstream{Name: "priority-9", URL: slow.URL, Priority: 9},
		Upstream{Name: "priority-0", URL: fast.URL, Priority: 0},
	)

	resp := doGet(t, h, "/health")
	if got := resp.Header.Get("X-Served-By"); got != nFast {
		t.Errorf("应按 priority 升序选上游：期望 %q，实际 %q", nFast, got)
	}
}

// 全部上游都挂 —— 必须如实返回 503，绝不能假装成功
func TestAllUpstreamsDown(t *testing.T) {
	s1, _ := newUpstream(t, "p1", http.StatusServiceUnavailable)
	s2, _ := newUpstream(t, "p2", http.StatusBadGateway)

	h := newGateway(t,
		Upstream{Name: "p1", URL: s1.URL, Priority: 0},
		Upstream{Name: "p2", URL: s2.URL, Priority: 1},
	)

	resp := doGet(t, h, "/chat")
	if resp.StatusCode != http.StatusServiceUnavailable {
		t.Fatalf("全部上游挂掉时应返回 503，实际 %d", resp.StatusCode)
	}
	body := readBody(t, resp)
	if !strings.Contains(body, "all upstreams unavailable") {
		t.Errorf("响应体应说明全部上游不可用，实际 %q", body)
	}
}

// 4xx 不该触发 failover —— 那是客户端的问题，换上游也救不了
func TestClientErrorDoesNotFailover(t *testing.T) {
	s1, _ := newUpstream(t, "primary", http.StatusNotFound)
	s2, n2 := newUpstream(t, "backup", 200)

	h := newGateway(t,
		Upstream{Name: "primary", URL: s1.URL, Priority: 0},
		Upstream{Name: "backup", URL: s2.URL, Priority: 1},
	)

	resp := doGet(t, h, "/nope")
	if resp.StatusCode != http.StatusNotFound {
		t.Errorf("404 应原样返回，不该 failover。实际 %d", resp.StatusCode)
	}
	if served := resp.Header.Get("X-Served-By"); served == n2 {
		t.Error("404 不该切换上游 —— 客户端错误换上游也救不了")
	}
}

// 禁用的上游必须被跳过
func TestDisabledUpstreamSkipped(t *testing.T) {
	disabled, _ := newUpstream(t, "disabled", 200)
	active, nActive := newUpstream(t, "active", 200)

	no := false
	h := newGateway(t,
		Upstream{Name: "disabled", URL: disabled.URL, Priority: 0, Enabled: &no},
		Upstream{Name: "active", URL: active.URL, Priority: 1},
	)

	resp := doGet(t, h, "/health")
	if got := resp.Header.Get("X-Served-By"); got != nActive {
		t.Errorf("被禁用的上游应跳过：期望 %q，实际 %q", nActive, got)
	}
}

// 配置错误应尽早暴露，而不是等到运行时才报错
func TestNoUpstreamsIsError(t *testing.T) {
	if _, err := New(Config{}); err == nil {
		t.Error("没有可用上游时应当返回错误")
	}
}

func TestBadURLIsError(t *testing.T) {
	_, err := New(Config{Upstreams: []Upstream{{Name: "x", URL: "://bad"}}})
	if err == nil {
		t.Error("非法 URL 应当返回错误")
	}
}

func readBody(t *testing.T, resp *http.Response) string {
	t.Helper()
	buf := make([]byte, 4096)
	n, _ := resp.Body.Read(buf)
	return string(buf[:n])
}
