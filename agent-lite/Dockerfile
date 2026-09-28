# 基础镜像走国内加速源。
# ⚠️ 原因：Docker Hub 直连不通，而 Docker Desktop 里配的 registry mirror
#    （docker.1ms.run）实测返回 403。把源写进 Dockerfile 更可控，
#    也避免了"换台机器就得重新配 mirror"。
#    换源时只需改这一行。
FROM docker.m.daocloud.io/library/python:3.11-slim

WORKDIR /app

# 安装依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Playwright 的 Python 包不包含浏览器内核；浏览器工具运行前必须安装 Chromium。
RUN python -m playwright install --with-deps chromium

# 复制源码
COPY . .

# chromadb 需要持久化，通过 volume 挂载
RUN mkdir -p /app/logs /app/chroma_db /app/models

EXPOSE 8000

CMD ["python", "main.py"]
