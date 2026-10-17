"""Conversation HTTP contracts, with temporary accounts and no model/network calls."""
import os
import sys
import tempfile
import unittest
import threading
from concurrent.futures import ThreadPoolExecutor
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

    def test_concurrent_turns_are_serial_per_conversation_and_release_on_error(self):
        first, second = self.create(), self.create()
        started, finish = threading.Event(), threading.Event()

        def turn(agent, inputs, cfg, **kwargs):
            if inputs["messages"][0].content == "wait":
                started.set()
                if not finish.wait(5):
                    raise RuntimeError("test timed out")
            kwargs["on_token"]("完成")

        def send(item, message):
            return self.client.post('/api/chat', headers=self.owner,
                                    json={"conversation_id": item["id"], "message": message})

        with patch.object(self.server, "get_web_agent", return_value=fake_agent()), \
             patch.object(self.server, "stream_turn", side_effect=turn), ThreadPoolExecutor() as pool:
            future = pool.submit(send, first, "wait")
            try:
                self.assertTrue(started.wait(5))
                self.assertEqual(send(first, "conflict").status_code, 409)
                state = self.client.get('/api/conversations/' + first["id"], headers=self.owner).json()
                self.assertTrue(state["running"])
                self.assertEqual(send(second, "independent").status_code, 200)
            finally:
                finish.set()
            self.assertEqual(future.result(timeout=5).status_code, 200)
            self.assertEqual(send(first, "retry").status_code, 200)

        with patch.object(self.server, "get_web_agent", return_value=fake_agent()), \
             patch.object(self.server, "stream_turn", side_effect=RuntimeError("private detail")):
            response = send(first, "failure")
            self.assertIn("服务暂时不可用", response.text)
            self.assertNotIn("private detail", response.text)
        with patch.object(self.server, "get_web_agent", return_value=fake_agent()), \
             patch.object(self.server, "stream_turn", side_effect=turn):
            self.assertEqual(send(first, "after failure").status_code, 200)

    def test_exhausted_conversation_returns_actionable_feedback(self):
        import config
        agent = fake_agent()
        snapshot = agent.get_state({})
        snapshot.values["thread_model_call_count"] = config.MODEL_CALL_THREAD_LIMIT
        with patch.object(self.server, "get_web_agent", return_value=agent), \
             patch.object(self.server, "stream_turn") as turn:
            state = self.client.get('/api/conversations/main', headers=self.owner).json()
            self.assertTrue(state["exhausted"])
            response = self.client.post('/api/chat', headers=self.owner, json={"message": "hi"})
            self.assertEqual(response.status_code, 429)
            self.assertIn("新建会话", response.json()["detail"])
            turn.assert_not_called()
        with patch.object(self.server, "get_web_agent", return_value=fake_agent()), \
             patch.object(self.server, "stream_turn"):
            fresh = self.create()
            response = self.client.post('/api/chat', headers=self.owner,
                                        json={"message": "hi", "conversation_id": fresh["id"]})
            self.assertEqual(response.status_code, 200)

    def test_real_graph_limits_surface_without_network(self):
        from langchain.agents import create_agent
        from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
        from langchain_core.messages import AIMessage, HumanMessage
        from langchain_core.tools import tool
        from langgraph.checkpoint.memory import InMemorySaver
        from agent.middleware import get_call_limit_middlewares
        from agent.streaming import stream_turn
        import config

        class Model(FakeMessagesListChatModel):
            def bind_tools(self, tools, **kwargs):
                return self

        called = []

        @tool
        def echo(text: str) -> str:
            """Echo the test input."""
            called.append(text)
            return text

        calls = [{"name": "echo", "args": {"text": word}, "id": word, "type": "tool_call"}
                 for word in ("first", "second")]
        with patch.object(config, "MODEL_CALL_RUN_LIMIT", 1), \
             patch.object(config, "TOOL_CALL_RUN_LIMIT", 1):
            agent = create_agent(Model(responses=[AIMessage(content="", tool_calls=calls), AIMessage("结束")]),
                                 tools=[echo], middleware=get_call_limit_middlewares(),
                                 checkpointer=InMemorySaver())
            limits = []
            cfg = {"configurable": {"thread_id": "limit-test"}, "recursion_limit": 100}
            stream_turn(agent, {"messages": [HumanMessage("run")]}, cfg, lambda info: None,
                        on_limit=limits.append)
            self.assertEqual(called, ["first"])
            self.assertIn("tool", limits)
            self.assertIn("model", limits)
            # A fresh run must reset run counters and remain a valid tool-message chain.
            reply = stream_turn(agent, {"messages": [HumanMessage("continue")]}, cfg, lambda info: None)
            self.assertIn("结束", reply)


if __name__ == "__main__":
    unittest.main()
