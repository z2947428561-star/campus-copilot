#!/usr/bin/env bash
# 在 Linux/WSL 的项目根目录运行：bash scripts/backup_postgres.sh [备份目录]
set -euo pipefail
cd "$(dirname "$0")/.."
backup_dir="${1:-backups}"
mkdir -p "$backup_dir"
umask 077
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
tmp="$(mktemp "$backup_dir/campus-$stamp.XXXXXX.partial")"
target="${tmp%.partial}.dump"
trap 'rm -f -- "$tmp"' EXIT
docker compose exec -T postgres pg_dump -U campus -d campus -Fc > "$tmp"
test -s "$tmp"
mv -- "$tmp" "$target"
trap - EXIT
printf 'PostgreSQL backup: %s\n' "$target"
