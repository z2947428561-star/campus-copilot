"""Run the local Dorm Web, Express gateway and Campus Agent together."""
import argparse
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dorm", type=Path, default=Path.home() / "Desktop" / "XMUMDorm-2.0.0-LYZZ")
    parser.add_argument("--db-port", type=int, default=3306)
    parser.add_argument("--local-kb", action="store_true", help="Use the separately prepared Dorm Chroma profile")
    parser.add_argument("--existing-database", action="store_true",
                        help="Use Dorm's existing database configuration for real account login; no migrations or background jobs")
    args = parser.parse_args()
    dorm = args.dorm.resolve()
    node = shutil.which("node")
    vite = dorm / "frontend/node_modules/vite/bin/vite.js"
    if not node or not vite.exists() or not (dorm / "routes/agent.js").exists():
        parser.error("请先准备 Dorm Node 依赖和本轮接入代码")
    for port in (8001, 4040, 5173):
        with socket.socket() as probe:
            try:
                probe.bind(("127.0.0.1", port))
            except OSError:
                parser.error(f"端口 {port} 已占用，请先关闭对应本地开发服务再启动")
    shared = secrets.token_urlsafe(48)
    common = {**os.environ, "CAMPUS_AGENT_SHARED_SECRET": shared}
    memory = ROOT / "data/local/xmumdorm"
    memory.mkdir(parents=True, exist_ok=True)
    agent_env = {**common, "CAMPUS_ENV_OVERRIDE": "0", "MEMORY_BACKEND": "sqlite",
                 "MEMORY_DB_PATH": str(memory / "memory.db"), "LANGSMITH_TRACING": "false",
                 "XMUMDORM_API_URL": "http://127.0.0.1:4040"}
    if args.local_kb:
        from prepare_dorm_kb import local_kb_environment
        if not (memory / "kb_releases.db").is_file():
            parser.error("请先运行 scripts/prepare_dorm_kb.py")
        agent_env.update(local_kb_environment())
    # Default stays local-only. Real login can explicitly use Dorm's existing .env.
    dorm_env = {**common, "CAMPUS_AGENT_URL": "http://127.0.0.1:8001", "HOST": "127.0.0.1",
                "PORT": "4040", "NODE_ENV": "development", "ENABLE_BACKGROUND_JOBS": "0"}
    if not args.existing_database:
        dorm_env.update({"DATABASE_URL": "", "MYSQL_URL": "", "RAILWAY_MYSQL_URL": "",
                         "DB_HOST": "127.0.0.1", "DB_PORT": str(args.db_port)})
    children = []
    try:
        children.append(subprocess.Popen([sys.executable, "-m", "uvicorn", "src.server:app", "--host", "127.0.0.1", "--port", "8001"], cwd=ROOT, env=agent_env))
        children.append(subprocess.Popen([node, "server.js"], cwd=dorm, env=dorm_env))
        children.append(subprocess.Popen([node, str(vite), "--host", "127.0.0.1", "--port", "5173", "--strictPort"], cwd=dorm / "frontend", env={**common, "VITE_API_BASE_URL": ""}))
        login_note = "使用现有 Dorm 账号登录" if args.existing_database else "使用 Dorm 本地账号登录"
        print("\nDorm Web: http://127.0.0.1:5173/login\n" + login_note + "；Ctrl+C 关闭本次启动的三个进程。", flush=True)
        while all(child.poll() is None for child in children):
            time.sleep(.5)
        return 1
    except KeyboardInterrupt:
        return 0
    finally:
        for child in children:
            if child.poll() is None:
                child.terminate()
        for child in children:
            try: child.wait(timeout=8)
            except subprocess.TimeoutExpired: child.kill(); child.wait()


if __name__ == "__main__":
    raise SystemExit(main())
