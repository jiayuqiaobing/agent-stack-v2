// cmd/mockserver/main.go
//
// 测试用的 mock 上游 —— 用来验证网关的 failover 行为。
//
// 它不是产品代码，是**验证工具**：让"上游挂了"这件事变得可复现。
// 没有它，就只能靠真的把服务拔掉来测，既不可靠也没法自动化。
//
// 用法：
//   go run ./cmd/mockserver -addr :9001 -name up1 -mode ok
//   go run ./cmd/mockserver -addr :9002 -name up2 -mode ok
//
// 行为由 -mode 决定（也可以在请求里用 ?mode= 临时覆盖）：
//   ok       正常返回 200
//   refuse   直接拒绝（不监听，模拟连接被拒）
//   e503     返回 503（模拟上游服务不可用）
//   e429     返回 429（模拟限流）
//   slow     延迟 10 秒再返回（模拟超时）
//
// 所有响应都带 X-Served-By 头，便于验证"这次请求最终落到了哪个上游"。
package main

import (
	"flag"
	"fmt"
	"log"
	"net/http"
	"time"
)

func main() {
	addr := flag.String("addr", ":9001", "监听地址")
	name := flag.String("name", "mock", "上游名字，会写进 X-Served-By")
	mode := flag.String("mode", "ok", "默认行为：ok / e503 / e429 / slow")
	flag.Parse()

	mux := http.NewServeMux()

	// 所有路径都走同一个处理逻辑 —— 网关可能把 /health /chat 等任意路径转过来
	mux.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
		m := r.URL.Query().Get("mode")
		if m == "" {
			m = *mode
		}

		w.Header().Set("X-Served-By", *name)

		switch m {
		case "e503":
			log.Printf("[%s] %s %s → 503（模拟上游不可用）", *name, r.Method, r.URL.Path)
			http.Error(w, `{"error":"service unavailable","upstream":"`+*name+`"}`, http.StatusServiceUnavailable)

		case "e429":
			log.Printf("[%s] %s %s → 429（模拟限流）", *name, r.Method, r.URL.Path)
			w.Header().Set("Retry-After", "10")
			http.Error(w, `{"error":"rate limited","upstream":"`+*name+`"}`, http.StatusTooManyRequests)

		case "slow":
			log.Printf("[%s] %s %s → 延迟 10s", *name, r.Method, r.URL.Path)
			time.Sleep(10 * time.Second)
			fmt.Fprintf(w, `{"ok":true,"upstream":%q,"note":"slow"}`, *name)

		default:
			log.Printf("[%s] %s %s → 200", *name, r.Method, r.URL.Path)
			fmt.Fprintf(w, `{"ok":true,"upstream":%q,"path":%q}`, *name, r.URL.Path)
		}
	})

	log.Printf("mock 上游 [%s] 启动 → %s（默认 mode=%s）", *name, *addr, *mode)
	if err := http.ListenAndServe(*addr, mux); err != nil {
		log.Fatalf("mock 上游启动失败：%v", err)
	}
}
