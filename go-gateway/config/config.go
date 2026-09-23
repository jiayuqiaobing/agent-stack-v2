// config/config.go
//
// 从 .env 读基础配置，从 JSON 文件读上游列表（failover 用）。
package config

import (
	"encoding/json"
	"fmt"
	"os"
	"sort"

	"github.com/joho/godotenv"

	"go-gateway/proxy"
)

var (
	AgentLiteURL  string // Python Agent 地址（完整 URL）
	GatewayPort   string // Go 网关监听端口
	OpenAIKey     string
	OpenAIBaseURL string
	ConfigPath    string // 上游配置文件路径
)

// 默认配置路径
const defaultConfigPath = "upstreams.json"

func Load() error {
	// 加载 agent-stack/.env（从 go-gateway/ 回到项目根目录）
	if err := godotenv.Load("../.env"); err != nil {
		// .env 缺失不算致命（Docker 环境用 env_file 注入）
		println("[config] 未找到 ../.env，使用系统环境变量")
	}

	// Python Agent 地址 —— 本机运行和容器运行是两个不同的地址：
	//   本机：http://localhost:8000
	//   容器：http://agent-lite:8000 （服务名，容器内 localhost 指向自己）
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

	ConfigPath = os.Getenv("GATEWAY_CONFIG")
	if ConfigPath == "" {
		ConfigPath = defaultConfigPath
	}

	return nil
}

// LoadUpstreams 读取上游配置
//
// 两种来源，按优先级：
//  1. JSON 配置文件（GATEWAY_CONFIG 指定，默认 upstreams.json）
//  2. 没有配置文件时，退化为单上游 —— 就是 AGENT_LITE_HOST 指向的那个
//
// 第 2 条保证"不配多上游也能跑"，failover 是可选增强而不是必需依赖。
func LoadUpstreams() (proxy.Config, error) {
	cfg := proxy.Config{}

	data, err := os.ReadFile(ConfigPath)
	if err != nil {
		// 没有配置文件 → 单上游模式
		fmt.Printf("[config] 未找到 %s，使用单上游模式（无 failover）\n", ConfigPath)
		cfg.Upstreams = []proxy.Upstream{
			{Name: "agent-lite", URL: AgentLiteURL, Priority: 0},
		}
		return cfg, nil
	}

	if err := json.Unmarshal(data, &cfg); err != nil {
		return cfg, fmt.Errorf("解析 %s 失败：%w", ConfigPath, err)
	}

	if len(cfg.Upstreams) == 0 {
		return cfg, fmt.Errorf("%s 里没有配置任何上游", ConfigPath)
	}

	// 校验每个上游的 URL
	enabled := 0
	for i := range cfg.Upstreams {
		u := &cfg.Upstreams[i]
		if u.Name == "" {
			u.Name = fmt.Sprintf("upstream-%d", i+1)
		}
		if u.URL == "" {
			return cfg, fmt.Errorf("上游 %s 缺少 url 字段", u.Name)
		}
		if u.Enabled == nil || *u.Enabled {
			enabled++
		}
	}
	if enabled == 0 {
		return cfg, fmt.Errorf("%s 里所有上游都被禁用了", ConfigPath)
	}

	sort.SliceStable(cfg.Upstreams, func(i, j int) bool {
		return cfg.Upstreams[i].Priority < cfg.Upstreams[j].Priority
	})

	return cfg, nil
}
