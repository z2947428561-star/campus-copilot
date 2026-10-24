# Campus Copilot Agent 镜像(Railway 部署用)
# 依赖 knowledge base 三个文件随构建上下文提供:kb_data/{chroma/, kb_releases.db, guides.db}
# 它们是本地生成物,不入 git —— 部署走 `railway up` 直传本机构建上下文。
FROM python:3.13-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# 依赖层(代码改动不重装依赖)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 代码与构建期数据(种子 → campus.db 在镜像内重建;本地专属种子缺失时自动跳过)
COPY src/ src/
COPY scripts/ scripts/
COPY data/structured/ data/structured/
RUN python scripts/init_db.py

# 静态前端目录(server 启动时 mount /assets 需要它存在)
COPY frontend/ frontend/

# 知识库三件套(政策向量索引 / 发布登记 / 指南正文),运行期只读
COPY kb_data/ kb_data/

EXPOSE 8000

# Railway 注入 PORT;本地 docker run 时默认 8000
CMD ["sh", "-c", "python -m uvicorn src.server:app --host 0.0.0.0 --port ${PORT:-8000}"]
