#!/usr/bin/env bash
# 一次性把现有独立 PostgreSQL 容器改为仅 127.0.0.1:5432 可访问。
# 保留原容器 postgres-before-local-bind 供人工回滚；不删除 pgdata 卷。
set -euo pipefail

old_name=postgres-before-local-bind
if docker container inspect "$old_name" >/dev/null 2>&1; then
  echo "拒绝执行：回滚容器 $old_name 已存在" >&2
  exit 1
fi
if ! docker container inspect postgres >/dev/null 2>&1; then
  echo "拒绝执行：找不到原 postgres 容器" >&2
  exit 1
fi

image="$(docker inspect postgres --format '{{.Image}}')"
password="$(docker inspect postgres --format '{{range .Config.Env}}{{println .}}{{end}}' | sed -n 's/^POSTGRES_PASSWORD=//p')"
if [[ -z "$password" ]]; then
  echo "拒绝执行：原容器未设置 POSTGRES_PASSWORD" >&2
  exit 1
fi

rollback() {
  docker rm -f postgres >/dev/null 2>&1 || true
  docker rename "$old_name" postgres
  docker start postgres >/dev/null
}

docker stop postgres >/dev/null
docker rename postgres "$old_name"
if ! docker run -d --name postgres --restart unless-stopped \
    --mount type=volume,source=pgdata,target=/var/lib/postgresql/data \
    -e POSTGRES_USER=postgres -e POSTGRES_PASSWORD="$password" \
    -p 127.0.0.1:5432:5432 "$image" >/dev/null; then
  rollback
  exit 1
fi

ready=0
for _ in $(seq 1 30); do
  if docker exec postgres pg_isready -U postgres >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 1
done
if [[ "$ready" != 1 ]]; then
  echo "新容器未就绪，恢复原容器" >&2
  rollback
  exit 1
fi
echo "PostgreSQL 已限制到 127.0.0.1:5432；原容器保留为 $old_name。"
