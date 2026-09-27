"""离线验证登录限流、独立用户名和成功后的计数清除。"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


class LoginRateLimitTest(unittest.TestCase):
    def test_login_rate_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = {
                "CAMPUS_SKIP_DOTENV": "1",
                "MEMORY_BACKEND": "sqlite",
                "MEMORY_DB_PATH": str(Path(tmp) / "auth.db"),
                "LANGSMITH_TRACING": "false",
            }
            with patch.dict(os.environ, settings):
                from fastapi.testclient import TestClient
                import auth
                from server import app

                with patch.object(auth.config, "LOGIN_FAILURE_LIMIT", 3), TestClient(app) as client:
                    auth._login_attempts.clear()
                    for name in ("rate-alice", "rate-bob"):
                        response = client.post("/api/register", json={"username": name, "password": "test-password"})
                        self.assertEqual(response.status_code, 200, response.text)

                    for _ in range(3):
                        response = client.post("/api/login", json={"username": "rate-alice", "password": "wrong"})
                        self.assertEqual(response.status_code, 401)
                    response = client.post("/api/login", json={"username": "rate-alice", "password": "test-password"})
                    self.assertEqual(response.status_code, 429)
                    self.assertIn("Retry-After", response.headers)
                    response = client.post("/api/login", json={"username": "rate-bob", "password": "test-password"})
                    self.assertEqual(response.status_code, 200)

                    # 窗口过后允许重试，成功即清除失败记录。
                    with auth._login_lock:
                        auth._login_attempts["rate-alice"].clear()
                    response = client.post("/api/login", json={"username": "rate-alice", "password": "test-password"})
                    self.assertEqual(response.status_code, 200)
                    self.assertNotIn("rate-alice", auth._login_attempts)


if __name__ == "__main__":
    unittest.main()
