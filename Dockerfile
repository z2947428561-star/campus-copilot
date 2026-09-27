# Campus Copilot 镜像
# 已于 2026-09-26 在 WSL Docker 构建通过，并验证镜像内种子数据库。
FROM python:3.13-slim

WORKDIR /app

# 依赖(利用层缓存:代码改动不重装依赖)
# requirements.txt 现已包含 fastapi / uvicorn / pymilvus / langchain-milvus /
# langgraph-checkpoint-postgres / psycopg —— 旧版这些全写在注释里,
# 结果镜像内 pip install 成功但没有 uvicorn,CMD 直接失败。
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 代码 + 数据(种子库 campus.db、RAG 文档与 Chroma 过渡索引;敏感 .env 不进镜像)
# 向量数据在 Milvus 里(compose 的 milvus_data 卷),不随镜像走 ——
# 首次起容器后必须跑一次: docker compose exec app python scripts/build_kb.py
COPY src/ src/
COPY data/ data/
COPY scripts/ scripts/

# campus.db 是生成物，构建镜像时从版本化的种子数据重建。
RUN python scripts/init_db.py

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "src.server:app", "--host", "0.0.0.0", "--port", "8000"]
