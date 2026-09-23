// proxy/proxy.go
// 反向代理 — httputil.ReverseProxy 封装为 gin.HandlerFunc
package proxy

import (
	"net/http"
	"net/http/httputil"
	"net/url"

	"github.com/gin-gonic/gin"
)

// New 创建一个反向代理 handler，将请求转发到 targetURL
// targetURL 示例: "http://localhost:8000"
func New(targetURL string) (gin.HandlerFunc, error) {
	target, err := url.Parse(targetURL)
	if err != nil {
		return nil, err
	}

	rp := httputil.NewSingleHostReverseProxy(target)

	// 保留原始请求的 Host 头（agent-lite 不需要改 Host，但保持透明）
	originalDirector := rp.Director
	rp.Director = func(req *http.Request) {
		originalDirector(req)
		req.Host = target.Host
	}

	// SSE 流式响应不能缓冲，需要 Flush
	rp.FlushInterval = -1 // 每次 Write 都 Flush

	return func(c *gin.Context) {
		rp.ServeHTTP(c.Writer, c.Request)
	}, nil
}
