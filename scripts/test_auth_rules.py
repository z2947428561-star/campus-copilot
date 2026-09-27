"""离线验证新账号格式、密码复杂度，以及旧账号继续登录。"""
import os
import secrets
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


class AuthRulesTest(unittest.TestCase):
    def test_registration_rules_and_legacy_login(self):
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

                with TestClient(app) as client:
                    password = "Abcdefg1"
                    for username in (
                        "tST2601001", "TS2601001", "TST2600001",
                        "TST2613001", "TST260100", "TST260100A", "TST26010１1",
                    ):
                        response = client.post("/api/register", json={"username": username, "password": password})
                        self.assertEqual(response.status_code, 400, username)

                    for weak_password in ("Abcdef1", "abcdefgh", "12345678", "密码密码12345678"):
                        response = client.post("/api/register", json={
                            "username": "TST2601001", "password": weak_password,
                        })
                        self.assertEqual(response.status_code, 400, weak_password)

                    response = client.post("/api/register", json={
                        "username": "TST2601001", "password": password,
                    })
                    self.assertEqual(response.status_code, 200, response.text)
                    self.assertEqual(response.json()["user_id"], "TST2601001")
                    response = client.post("/api/login", json={
                        "username": "TST2601001", "password": password,
                    })
                    self.assertEqual(response.status_code, 200, response.text)

                    salt = secrets.token_hex(16)
                    with auth._conn() as conn:
                        conn.execute(
                            "INSERT INTO web_users (username, password_hash, salt, created_at) VALUES (?, ?, ?, ?)",
                            ("legacy-user", auth._hash_password("old-password", salt), salt, time.time()),
                        )
                        conn.commit()
                    response = client.post("/api/login", json={
                        "username": "legacy-user", "password": "old-password",
                    })
                    self.assertEqual(response.status_code, 200, response.text)


if __name__ == "__main__":
    unittest.main()
