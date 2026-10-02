"""Run offline regression checks in an isolated copy of public project files."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHECKS = (
    "test_auth_rules.py",
    "test_auth_rate_limit.py",
    "test_reset_local_password.py",
    "test_student_data.py",
    "test_server_security.py",
    "test_chroma_rebuild.py",
    "test_course_recommendations.py",
)


def main() -> int:
    env = os.environ.copy()
    env.update({
        "CAMPUS_SKIP_DOTENV": "1",
        "MEMORY_BACKEND": "sqlite",
        "LANGSMITH_TRACING": "false",
        "ANONYMIZED_TELEMETRY": "False",
        "PYTHONUTF8": "1",
    })
    with tempfile.TemporaryDirectory(prefix="campus-offline-") as tmp:
        workspace = Path(tmp)
        for folder in ("src", "scripts", "data/structured", "data/raw_docs"):
            shutil.copytree(
                ROOT / folder, workspace / folder,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".env", "*.db*", "*.local.json"),
            )
        env["MEMORY_DB_PATH"] = str(workspace / "data" / "memory.db")
        for script in ("init_db.py", *CHECKS):
            print(f"\n[offline] {script}", flush=True)
            result = subprocess.run(
                [sys.executable, str(workspace / "scripts" / script)],
                cwd=workspace, env=env, check=False,
            )
            if result.returncode:
                print(f"[offline] FAILED: {script}", flush=True)
                return result.returncode
    print(f"\n[offline] Passed all {len(CHECKS)} check files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
