# 本机数据库端口

2026-09-27 已将独立 PostgreSQL、Milvus、MinIO 的宿主机端口限制到
`127.0.0.1`。本目录保留已有本机数据库的端口约束；项目根目录的应用
镜像、整套 Compose 和 HTTPS 代理已移除。应用直接在本机 Python 环境运行。

以下容器名和 WSL 路径是现有开发机的记录，不是新克隆用户必须照搬的配置。
新环境可以先使用 README 中的 SQLite + Chroma 路径，不必安装数据库容器。

- PostgreSQL：现用容器 `postgres` 挂载原命名卷 `pgdata`，监听
  `127.0.0.1:5432`。原容器停用并保留为 `postgres-before-local-bind`，
  已设置为不自动重启，供排障回滚；不要对其执行 `docker rm -v` 或删除 `pgdata`。
- Milvus：原 Compose 位于 WSL 的 `/home/kiyotaka/milvus/docker-compose.yml`。
  其 `docker-compose.override.yml` 是指向本目录
  `milvus-local-ports.yml` 的符号链接。因此在该 WSL 目录直接运行
  `docker compose up -d` 仍会采用本机绑定；不要仅用 `-f docker-compose.yml`
  绕过默认 override。
- MinIO 控制台与 API 分别为 `127.0.0.1:9001`、`:9000`；Milvus 为
  `127.0.0.1:19530`、`:9091`。etcd 从未映射宿主机端口。

核验：

```bash
docker ps --format '{{.Names}} {{.Ports}}'
cd /home/kiyotaka/milvus && docker compose config --quiet
```

端口调整前后已核对 PostgreSQL 的 `campus`/`campus_test` 数据库以及
Milvus `campus_copilot.xmum_policies` 的 106 个片段。重新克隆本项目到
新位置时，需要重新建立 WSL 的符号链接，或显式用 `-f` 加载覆盖文件。
