# ========== 构建阶段 ==========
FROM docker.m.daocloud.io/library/golang:1.26-alpine AS builder

WORKDIR /build

# 先复制依赖文件，利用 Docker 缓存层
COPY go.mod go.sum ./
RUN go mod download

# 复制源码并编译
COPY . .
RUN CGO_ENABLED=0 go build -o gateway main.go

# ========== 运行阶段 ==========
FROM docker.m.daocloud.io/library/alpine:3.21

WORKDIR /app

COPY --from=builder /build/gateway .

# 默认从 docker-compose env_file 读取环境变量
ENV GATEWAY_PORT=3000
ENV AGENT_LITE_PORT=8000

EXPOSE 3000

CMD ["./gateway"]
