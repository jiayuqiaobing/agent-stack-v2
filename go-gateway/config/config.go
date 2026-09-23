// config/config.go
// 从 agent-stack/.env 加载统一配置
package config

import (
	"os"

	"github.com/joho/godotenv"
)

var (
	AgentLiteURL  string // Python Agent 地址（完整 URL）
	GatewayPort   string // Go 网关监听端口
	OpenAIKey     string
	OpenAIBaseURL string
)

func Load() error {
	// 加载 agent-stack/.env（从 go-gateway/ 回到项目根目录）
	if err := godotenv.Load("../.env"); err != nil {
		// .env 文件缺失不算致命错误（Docker 环境可能用 env_file 注入）
		// 但打印警告
		println("[config] 未找到 ../.env，使用系统环境变量")
	}

	// Python Agent 地址 —— 本机运行和容器运行是两个不同的地址：
	//   本机：http://localhost:8000
	//   容器：http://agent-lite:8000 （docker-compose 服务名，容器内 localhost 指向自己）
	// 修复历史：v1 写死 localhost，导致容器部署时网关永远连不上 agent-lite。
	agentHost := os.Getenv("AGENT_LITE_HOST")
	if agentHost == "" {
		agentHost = "localhost"
	}

	agentPort := os.Getenv("AGENT_LITE_PORT")
	if agentPort == "" {
		agentPort = "8000"
	}

	AgentLiteURL = "http://" + agentHost + ":" + agentPort

	GatewayPort = os.Getenv("GATEWAY_PORT")
	if GatewayPort == "" {
		GatewayPort = "3000"
	}

	OpenAIKey = os.Getenv("OPENAI_API_KEY")
	OpenAIBaseURL = os.Getenv("OPENAI_BASE_URL")

	return nil
}
