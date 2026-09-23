// middleware/logging.go
// Gin 中间件：请求日志
package middleware

import (
	"log"
	"time"

	"github.com/gin-gonic/gin"
)

// Logger 记录每个请求的 method、path、status、latency
func Logger() gin.HandlerFunc {
	return func(c *gin.Context) {
		start := time.Now()

		c.Next() // 执行后续 handler

		latency := time.Since(start)
		status := c.Writer.Status()

		log.Printf("[网关] %s %s → %d (%s)",
			c.Request.Method,
			c.Request.URL.Path,
			status,
			latency.Round(time.Millisecond),
		)
	}
}
