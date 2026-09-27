"""离线验证发布前 API 边界与错误信息脱敏。"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


class ServerSecurityTest(unittest.TestCase):
    def test_api_guards(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = {
                "CAMPUS_SKIP_DOTENV": "1",
                "MEMORY_BACKEND": "sqlite",
                "MEMORY_DB_PATH": str(Path(tmp) / "memory.db"),
                "LANGSMITH_TRACING": "false",
            }
            with patch.dict(os.environ, settings):
                from fastapi.testclient import TestClient
                import server

                with TestClient(server.app) as client:
                    page = client.get("/")
                    self.assertEqual(page.status_code, 200)
                    self.assertEqual(page.headers["cache-control"], "no-store")

                    weak = client.post("/api/register", json={
                        "username": "SEC2509001", "password": "short"
                    })
                    self.assertEqual(weak.status_code, 400)
                    response = client.post("/api/register", json={
                        "username": "SEC2509001", "password": "Testpass123"
                    })
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.headers["cache-control"], "no-store")
                    self.assertEqual(response.headers["x-content-type-options"], "nosniff")
                    self.assertEqual(response.headers["x-frame-options"], "DENY")
                    headers = {"Authorization": "Bearer " + response.json()["token"]}

                    too_long = client.post("/api/chat", headers=headers,
                                           json={"message": "x" * 4001})
                    self.assertEqual(too_long.status_code, 422)
                    self.assertEqual(too_long.headers["cache-control"], "no-store")
                    with patch.object(server, "get_web_agent", return_value=object()), \
                         patch.object(server, "stream_turn", side_effect=RuntimeError("SECRET_DATABASE_URL")):
                        response = client.post("/api/chat", headers=headers, json={"message": "hi"})
                    self.assertEqual(response.status_code, 200)
                    self.assertIn("服务暂时不可用", response.text)
                    self.assertNotIn("SECRET_DATABASE_URL", response.text)


if __name__ == "__main__":
    unittest.main()
