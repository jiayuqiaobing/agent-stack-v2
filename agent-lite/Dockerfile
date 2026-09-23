FROM python:3.11-slim

WORKDIR /app

# 安装依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制源码
COPY . .

# chromadb 需要持久化，通过 volume 挂载
RUN mkdir -p /app/logs /app/chroma_db /app/models

EXPOSE 8000

CMD ["python", "main.py"]
