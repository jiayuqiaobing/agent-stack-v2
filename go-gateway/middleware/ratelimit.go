// middleware/ratelimit.go
// Gin 中间件：令牌桶限流
package middleware

import (
	"net/http"
	"sync"

	"github.com/gin-gonic/gin"
	"golang.org/x/time/rate"
)

// RateLimiter 返回一个基于客户端 IP 的令牌桶限流中间件
// rps: 每秒允许的请求数
// burst: 允许的突发请求数
func RateLimiter(rps float64, burst int) gin.HandlerFunc {
	// IP → *rate.Limiter 映射
	limiters := make(map[string]*rate.Limiter)
	var mu sync.Mutex

	return func(c *gin.Context) {
		ip := c.ClientIP()

		mu.Lock()
		lim, exists := limiters[ip]
		if !exists {
			lim = rate.NewLimiter(rate.Limit(rps), burst)
			limiters[ip] = lim
		}
		mu.Unlock()

		if !lim.Allow() {
			c.AbortWithStatusJSON(http.StatusTooManyRequests, gin.H{
				"error": "请求过于频繁，请稍后再试",
			})
			return
		}

		c.Next()
	}
}
