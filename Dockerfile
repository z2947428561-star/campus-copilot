# Campus Copilot 镜像
# 注意:本文件按 Docker 最佳实践编写,但开发机(Windows)无 Docker,尚未本地验证;
# 首次部署时按 docker-compose.yml 顶部注释核对。
FROM python:3.13-slim

WORKDIR /app

# 先装依赖(利用层缓存:代码改动不重装依赖)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 代码 + 数据(seed 数据库、RAG 文档与 Chroma 索引;敏感 .env 不进镜像)
COPY src/ src/
COPY data/ data/

EXPOSE 8000

# 容器内直连宿主机 Postgres 用 host.docker.internal(见 compose)
CMD ["python", "-m", "uvicorn", "src.server:app", "--host", "0.0.0.0", "--port", "8000"]
