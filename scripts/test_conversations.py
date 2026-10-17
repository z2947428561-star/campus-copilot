"""Conversation HTTP contracts, with temporary accounts and no model/network calls."""
import os
import sys
import tempfile
import unittest
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def fake_agent(messages=(), actions=(), version="checkpoint-1"):
    from langgraph.types import Interrupt
    interrupts = (Interrupt(value={
        "action_requests": list(actions),
        "review_configs": [{"allowed_decisions": ["approve", "reject"]} for _ in actions],
    }),) if actions else ()
    snapshot = SimpleNamespace(values={"messages": list(messages)}, interrupts=interrupts,
                               config={"configurable": {"checkpoint_id": version}})
    return SimpleNamespace(get_state=lambda cfg: snapshot)


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

        with patch.object(self.server, "get_web_agent", return_value=fake_agent()), \
             patch.object(self.server, "stream_turn", side_effect=turn):
            for body in ({"message": "old"}, {"message": "new", "conversation_id": created["id"]}):
                response = self.client.post("/api/chat", headers=self.owner, json=body)
                self.assertEqual(response.status_code, 200)
                self.assertIn("你好", response.text)
        self.assertEqual(seen[0], (default_thread_id("CVS2601001"), "CVS2601001"))
        self.assertNotEqual(seen[0][0], seen[1][0])
        self.assertEqual(seen[1][1], "CVS2601001")

    def test_history_projects_chat_and_rejects_other_owner(self):
        from langchain_core.messages import AIMessage, HumanMessage, ToolMessage, SystemMessage
        created = self.create()
        agent = fake_agent([SystemMessage("internal"), HumanMessage("我的课表"),
                            ToolMessage("private tool details", tool_call_id="1"), AIMessage("周一上课")])
        with patch.object(self.server, "get_web_agent", return_value=agent):
            response = self.client.get('/api/conversations/' + created["id"], headers=self.owner)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["messages"], [
                {"role": "user", "text": "我的课表"}, {"role": "assistant", "text": "周一上课"}])
            self.assertEqual(response.json()["checkpoint_id"], "checkpoint-1")
            denied = self.client.get('/api/conversations/' + created["id"], headers=self.other)
            self.assertEqual(denied.status_code, 404)

    def test_pending_restore_and_versioned_decisions(self):
        created = self.create()
        actions = [{"name": "calculate_gpa", "args": {"semester": value}} for value in ("a", "b")]
        agent = fake_agent(actions=actions)
        base = {"conversation_id": created["id"], "checkpoint_id": "checkpoint-1"}
        with patch.object(self.server, "get_web_agent", return_value=agent), \
             patch.object(self.server, "stream_turn") as turn:
            state = self.client.get('/api/conversations/' + created["id"], headers=self.owner).json()
            self.assertEqual(len(state["pending"]), 2)
            self.assertEqual(state["pending"][0]["args"], {"semester": "a"})
            for body, expected in (
                ({**base, "message": "new"}, 409),
                ({**base, "resume": True}, 422),
                ({**base, "decisions": [{"type": "approve"}]}, 422),
                ({**base, "checkpoint_id": "old", "decisions": [{"type": "approve"}] * 2}, 409),
                ({**base, "decisions": [{"type": "edit"}] * 2}, 422),
            ):
                response = self.client.post('/api/chat', headers=self.owner, json=body)
                self.assertEqual(response.status_code, expected, response.text)
            turn.assert_not_called()
            response = self.client.post('/api/chat', headers=self.owner,
                                        json={**base, "decisions": [{"type": "reject"}] * 2})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(turn.call_args.args[1].resume["decisions"], [{"type": "reject"}] * 2)

    def test_invalid_inputs_and_resume_without_pending(self):
        with patch.object(self.server, "get_web_agent", return_value=fake_agent()), \
             patch.object(self.server, "stream_turn") as turn:
            for body in ({}, {"message": " "}, {"message": "hi", "resume": True}):
                response = self.client.post('/api/chat', headers=self.owner, json=body)
                self.assertEqual(response.status_code, 422, response.text)
            response = self.client.post('/api/chat', headers=self.owner,
                                        json={"resume": True, "checkpoint_id": "checkpoint-1"})
            self.assertEqual(response.status_code, 409, response.text)
            turn.assert_not_called()


if __name__ == "__main__":
    unittest.main()
