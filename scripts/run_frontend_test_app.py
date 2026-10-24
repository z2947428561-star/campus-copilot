"""Start a local browser-test app with temporary personal data and no model calls."""
from __future__ import annotations

import os
import argparse
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--summarize', action='store_true', help='使用真实摘要中间件和虚构摘要模型验证历史保留')
    parser.add_argument('--port', type=int, default=18765)
    args = parser.parse_args()
    sys.path.insert(0, str(ROOT))
    os.environ.update({
        "CAMPUS_SKIP_DOTENV": "1",
        "MEMORY_BACKEND": "sqlite",
        "LANGSMITH_TRACING": "false",
        "MODEL_CALL_THREAD_LIMIT": "6",
        "MODEL_CALL_RUN_LIMIT": "4",
        "LLM_FALLBACK_PROVIDER": "none",
    })
    with tempfile.TemporaryDirectory(prefix="campus-browser-") as tmp:
        os.environ["MEMORY_DB_PATH"] = str(Path(tmp) / "memory.db")
        os.environ["KB_BACKEND"] = "chroma"
        os.environ["CHROMA_DIR"] = str(Path(tmp) / "missing-chroma")
        os.environ["KB_REGISTRY_PATH"] = str(Path(tmp) / "kb_releases.db")
        from browser_fixtures import create_catalog, add_test_semester
        catalog_path = Path(tmp) / "campus.db"
        create_catalog(catalog_path)
        add_test_semester(catalog_path)
        import uvicorn
        from src import server
        import student_data
        student_data.CATALOG_DB = catalog_path
        from fake_chat_agent import build_agent

        server._agent = build_agent(summarize=args.summarize)
        server._dorm_agent = server._agent
        print(f"Browser-test app: http://127.0.0.1:{args.port}/ (temporary accounts; offline fake model)", flush=True)
        uvicorn.run(server.app, host="127.0.0.1", port=args.port, log_level="warning", access_log=False)


if __name__ == "__main__":
    main()
