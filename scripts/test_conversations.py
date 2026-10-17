"""Conversation HTTP contracts, with temporary accounts and no model/network calls."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


class ConversationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix="campus-conversations-")
        cls.env = patch.dict(os.environ, {
            "CAMPUS_SKIP_DOTENV": "1", "MEMORY_BACKEND": "sqlite",
            "MEMORY_DB_PATH": str(Path(cls.tmp.name) / "memory.db"),
            "LANGSMITH_TRACING": "false",
        })
        cls.env.start()
        from fastapi.testclient import TestClient
        import server
        cls.server = server
        cls.client = TestClient(server.app)
        cls.client.__enter__()
        cls.headers = {}
        for username in ("CVS2601001", "CVS2601002"):
            response = cls.client.post("/api/register", json={
                "username": username, "password": "Testpass123",
            })
            assert response.status_code == 200, response.text
            cls.headers[username] = {"Authorization": "Bearer " + response.json()["token"]}
        cls.owner = cls.headers["CVS2601001"]
        cls.other = cls.headers["CVS2601002"]

    @classmethod
    def tearDownClass(cls):
        cls.client.__exit__(None, None, None)
        cls.env.stop()
        cls.tmp.cleanup()

    def create(self):
        response = self.client.post("/api/conversations", headers=self.owner)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_create_list_and_owner_isolation(self):
        self.assertEqual(self.client.get("/api/conversations").status_code, 401)
        initial = self.client.get("/api/conversations", headers=self.owner)
        self.assertEqual(initial.status_code, 200)
        self.assertIn("main", [item["id"] for item in initial.json()["conversations"]])
        first, second = self.create(), self.create()
        self.assertNotEqual(first["id"], second["id"])
        own_ids = [item["id"] for item in self.client.get(
            "/api/conversations", headers=self.owner).json()["conversations"]]
        self.assertIn(first["id"], own_ids)
        self.assertIn(second["id"], own_ids)
        other_ids = [item["id"] for item in self.client.get(
            "/api/conversations", headers=self.other).json()["conversations"]]
        self.assertNotIn(first["id"], other_ids)
        with patch.object(self.server, "get_web_agent") as model:
            response = self.client.post("/api/chat", headers=self.other,
                                        json={"message": "secret", "conversation_id": first["id"]})
            self.assertEqual(response.status_code, 404)
            model.assert_not_called()

    def test_chat_uses_selected_or_legacy_thread(self):
        from agent.runtime import default_thread_id
        created = self.create()
        seen = []

        def turn(agent, inputs, cfg, **kwargs):
            seen.append((cfg["configurable"]["thread_id"], kwargs["context"].user_id))
            kwargs["on_token"]("你好")

        with patch.object(self.server, "get_web_agent", return_value=object()), \
             patch.object(self.server, "stream_turn", side_effect=turn):
            for body in ({"message": "old"}, {"message": "new", "conversation_id": created["id"]}):
                response = self.client.post("/api/chat", headers=self.owner, json=body)
                self.assertEqual(response.status_code, 200)
                self.assertIn("你好", response.text)
        self.assertEqual(seen[0], (default_thread_id("CVS2601001"), "CVS2601001"))
        self.assertNotEqual(seen[0][0], seen[1][0])
        self.assertEqual(seen[1][1], "CVS2601001")


if __name__ == "__main__":
    unittest.main()
