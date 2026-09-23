// main.go
// Go API 网关入口 — Gin 框架
// 反向代理到 agent-lite (Python FastAPI)，提供统一的日志、限流、健康检查
package main

import (
	"io"
	"log"
	"net/http"
	"os"
	"path/filepath"

	"github.com/gin-gonic/gin"

	"go-gateway/config"
	"go-gateway/middleware"
	"go-gateway/proxy"
)

func main() {
	// 加载配置
	if err := config.Load(); err != nil {
		log.Fatalf("配置加载失败：%v", err)
	}

	// 初始化日志文件 — 同时输出到控制台 + 文件（与 agent-lite 风格一致）
	logDir := filepath.Join("logs")
	os.MkdirAll(logDir, 0755)
	logFile, err := os.OpenFile(
		filepath.Join(logDir, "gateway.log"),
		os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0666,
	)
	if err != nil {
		log.Fatalf("无法创建日志文件：%v", err)
	}
	defer logFile.Close()
	log.SetOutput(io.MultiWriter(os.Stdout, logFile))

	log.Printf("Agent-Lite 地址：%s", config.AgentLiteURL)
	log.Printf("网关监听端口：%s", config.GatewayPort)

	// 创建反向代理 handler
	proxyHandler, err := proxy.New(config.AgentLiteURL)
	if err != nil {
		log.Fatalf("反向代理初始化失败：%v", err)
	}

	// 创建 Gin 引擎（使用 New() 避免 gin 内置 Logger 与我们自定义 Logger 重复）
	r := gin.New()
	r.Use(gin.Recovery()) // panic 恢复，防止进程崩溃

	// 注册全局中间件
	r.Use(middleware.Logger())
	r.Use(middleware.RateLimiter(10, 20)) // 每 IP 10 req/s，突发 20

	// ============================================
	// 显式路由
	// ============================================

	// 健康检查 — 本地返回 + 透传 agent-lite
	r.GET("/health", func(c *gin.Context) {
		// 本地健康信息
		local := gin.H{
			"gateway":   "healthy",
			"agent_url": config.AgentLiteURL,
		}

		// 透传 agent-lite 的健康检查
		resp, err := http.Get(config.AgentLiteURL + "/health")
		if err != nil {
			c.JSON(http.StatusOK, gin.H{
				"gateway": "healthy",
				"agent":   "unreachable",
				"error":   err.Error(),
			})
			return
		}
		defer resp.Body.Close()

		c.JSON(http.StatusOK, gin.H{
			"gateway":   "healthy",
			"agent":     "connected",
			"agent_url": config.AgentLiteURL,
		})
		_ = local // 后续可扩展返回更丰富的健康信息
	})

	// Agent 核心 API — 反向代理
	r.POST("/chat", proxyHandler)
	r.POST("/chat/stream", proxyHandler)
	r.GET("/sessions", proxyHandler)
	r.DELETE("/sessions/:id", proxyHandler)

	// Swagger 文档 — 反向代理
	r.Any("/docs/*any", proxyHandler)
	r.GET("/openapi.json", proxyHandler)

	// 聊天界面 + 静态文件 — 通配反向代理
	r.Any("/", proxyHandler)
	r.Any("/:any", func(c *gin.Context) {
		// 排除已注册的显式路由，其余透传
		proxyHandler(c)
	})

	// ============================================
	// 启动
	// ============================================

	log.Printf(" Go Gateway 启动 → http://localhost:%s", config.GatewayPort)
	if err := r.Run(":" + config.GatewayPort); err != nil {
		log.Fatalf("网关启动失败：%v", err)
	}
}
