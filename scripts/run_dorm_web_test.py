"""Run Web and gateway with fixture accounts; optionally use the real Agent."""
import os
import argparse
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
DORM = Path.home() / "Desktop" / "XMUMDorm-2.0.0-LYZZ"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live-agent", action="store_true", help="Use the real model and the isolated local Chroma profile; Dorm accounts remain fixtures")
    parser.add_argument('--agent-port', type=int, default=18765)
    parser.add_argument('--web-port', type=int, default=18766)
    args = parser.parse_args()
    if args.agent_port == args.web_port or any(not 1 <= p <= 65535 for p in (args.agent_port, args.web_port)):
        parser.error('测试端口必须有效且不相同')
    for port in (args.agent_port, args.web_port):
        with socket.socket() as probe:
            try: probe.bind(('127.0.0.1', port))
            except OSError: parser.error(f'测试端口 {port} 已占用；可指定其他端口，不关闭已有服务')
    env = {**os.environ, "CAMPUS_AGENT_SHARED_SECRET": secrets.token_urlsafe(48),
           "CAMPUS_AGENT_URL": f"http://127.0.0.1:{args.agent_port}", "PYTHONUTF8": "1",
           "CAMPUS_FIXTURE_PORT": str(args.web_port)}
    if args.live_agent:
        from prepare_dorm_kb import PROFILE, local_kb_environment
        if not (PROFILE / "kb_releases.db").is_file():
            parser.error("请先运行 scripts/prepare_dorm_kb.py")
        env.update({**local_kb_environment(), "MEMORY_BACKEND": "sqlite",
                    "MEMORY_DB_PATH": str(PROFILE / "live-memory.db"), "LLM_FALLBACK_PROVIDER": "none",
                    "LLM_MAX_RETRIES": "0", "LLM_TIMEOUT": "40", "LLM_MAX_TOKENS": "1200",
                    "MODEL_CALL_RUN_LIMIT": "4", "TOOL_CALL_RUN_LIMIT": "4", "DORM_AGENT_LIVE": "1"})
    children = []
    try:
        agent_command = ([sys.executable, "-m", "uvicorn", "src.server:app", "--host", "127.0.0.1", "--port", str(args.agent_port), "--no-access-log"]
                         if args.live_agent else [sys.executable, "scripts/run_frontend_test_app.py", "--port", str(args.agent_port)])
        children.append(subprocess.Popen(agent_command, cwd=ROOT, env=env))
        children.append(subprocess.Popen([shutil.which("node"), "scripts/run-agent-test-app.js"], cwd=DORM, env=env))
        while all(child.poll() is None for child in children): time.sleep(.5)
        return 1
    except KeyboardInterrupt:
        return 0
    finally:
        for child in children:
            if child.poll() is None: child.terminate()
        for child in children:
            try: child.wait(timeout=5)
            except subprocess.TimeoutExpired: child.kill(); child.wait()


if __name__ == "__main__":
    raise SystemExit(main())
