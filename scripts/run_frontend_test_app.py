"""Start a local browser-test app with temporary personal data and no model calls."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    sys.path.insert(0, str(ROOT))
    os.environ.update({
        "CAMPUS_SKIP_DOTENV": "1",
        "MEMORY_BACKEND": "sqlite",
        "LANGSMITH_TRACING": "false",
    })
    with tempfile.TemporaryDirectory(prefix="campus-browser-") as tmp:
        os.environ["MEMORY_DB_PATH"] = str(Path(tmp) / "memory.db")
        import uvicorn
        from fastapi import HTTPException
        from src import server

        def block_agent():
            raise HTTPException(status_code=503, detail="Browser tests must mock chat responses")

        server.get_web_agent = block_agent
        print("Browser-test app: http://127.0.0.1:18765/ (temporary accounts; chat blocked)", flush=True)
        uvicorn.run(server.app, host="127.0.0.1", port=18765, log_level="warning", access_log=False)


if __name__ == "__main__":
    main()
