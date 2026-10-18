"""HTTP and real HITL graph checks for immutable per-turn semester context."""
from datetime import date
import unittest
from unittest.mock import patch

from test_semester_data import SemesterFixture


class SemesterContextTest(SemesterFixture, unittest.TestCase):
    def test_semester_catalog_requires_login_and_marks_outside_defaults(self):
        self.assertEqual(self.client.get("/api/semesters").status_code, 401)
        with patch.object(self.semesters, "campus_today", return_value=date(2030, 1, 1)):
            data = self.client.get("/api/semesters", headers=self.alice).json()
        self.assertEqual({t["semester_id"] for t in data["semesters"]}, {"2026-09", "2027-04"})
        self.assertEqual(data["default_id"], "2027-04")
        self.assertTrue(all(not term["is_current"] for term in data["semesters"]))
        self.assertNotIn("storage_key", data["semesters"][0])

    def test_pending_turn_restores_original_semester_and_rejects_changed_scope(self):
        from langchain.agents import create_agent
        from langchain.agents.middleware import HumanInTheLoopMiddleware
        from langchain_core.language_models.chat_models import BaseChatModel
        from langchain_core.messages import AIMessage
        from langchain_core.outputs import ChatGeneration, ChatResult
        from langchain_core.tools import tool
        from langgraph.checkpoint.memory import InMemorySaver
        from langgraph.prebuilt import ToolRuntime
        from context import UserContext
        import server

        class ScopedModel(BaseChatModel):
            @property
            def _llm_type(self):
                return "scoped-test-model"

            def bind_tools(self, tools, **kwargs):
                return self

            def _generate(self, messages, **kwargs):
                if messages[-1].type == "tool":
                    message = AIMessage(content=messages[-1].content)
                else:
                    message = AIMessage(content="", tool_calls=[{"name": "calculate_gpa", "args": {},
                        "id": "semester-scope-test", "type": "tool_call"}])
                return ChatResult(generations=[ChatGeneration(message=message)])

        @tool
        def calculate_gpa(runtime: ToolRuntime[UserContext]) -> str:
            """Return only the runtime semester to prove resumed context."""
            return "confirmed-semester:" + str(runtime.context.semester_id)

        graph = create_agent(model=ScopedModel(), tools=[calculate_gpa], checkpointer=InMemorySaver(),
            context_schema=UserContext, middleware=[HumanInTheLoopMiddleware(interrupt_on={
                "calculate_gpa": {"allowed_decisions": ["approve", "reject"]}})])
        with patch.object(server, "_agent", graph):
            item = self.client.post("/api/conversations", headers=self.alice).json()
            cid = item["id"]
            result = self.client.post("/api/chat", headers=self.alice,
                json={"conversation_id": cid, "message": "算 GPA", "semester_id": "2026-09"})
            self.assertIn('"type": "interrupt"', result.text)
            detail = self.client.get("/api/conversations/" + cid, headers=self.alice).json()
            self.assertEqual(detail["semester_id"], "2026-09")
            resume = {"conversation_id": cid, "checkpoint_id": detail["checkpoint_id"], "decisions": [{"type": "approve"}]}
            wrong = self.client.post("/api/chat", headers=self.alice, json={**resume, "semester_id": "2027-04"})
            self.assertEqual(wrong.status_code, 409)
            correct = self.client.post("/api/chat", headers=self.alice, json=resume)
            self.assertIn("confirmed-semester:2026-09", correct.text)
            self.assertNotIn("confirmed-semester:2027-04", correct.text)


if __name__ == "__main__":
    unittest.main()
