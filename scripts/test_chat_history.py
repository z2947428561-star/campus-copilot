"""User-visible history must survive real context summarization and resume."""
from contextlib import ExitStack
from pathlib import Path
import unittest
from unittest.mock import patch

from test_semester_data import SemesterFixture


class ChatHistoryTest(SemesterFixture, unittest.TestCase):
    def create(self):
        return self.client.post('/api/conversations', headers=self.alice).json()['id']

    def detail(self, cid, headers=None):
        response = self.client.get('/api/conversations/' + cid, headers=headers or self.alice)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def graph(self, saver, *, summary=True, hitl=False):
        from langchain.agents import create_agent
        from langchain.agents.middleware import SummarizationMiddleware, HumanInTheLoopMiddleware
        from langchain_core.language_models.fake_chat_models import FakeListChatModel
        from langchain_core.tools import tool
        from fake_chat_agent import BrowserTestModel
        from context import UserContext

        @tool
        def calculate_gpa(semester: str = 'test') -> str:
            """Return fictional data for a history test."""
            return 'synthetic GPA'

        middleware = [SummarizationMiddleware(model=FakeListChatModel(responses=['synthetic-summary']),
            trigger=('messages', 6), keep=('messages', 2))] if summary else []
        if hitl:
            middleware.append(HumanInTheLoopMiddleware(interrupt_on={'calculate_gpa': {
                'allowed_decisions': ['approve', 'reject']}}))
        return create_agent(model=BrowserTestModel(), tools=[calculate_gpa], middleware=middleware,
                            checkpointer=saver, context_schema=UserContext)

    def send(self, cid, message):
        response = self.client.post('/api/chat', headers=self.alice,
            json={'conversation_id': cid, 'message': message, 'semester_id': '2026-09'})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertNotIn('"type": "error"', response.text)
        return response

    def test_real_summary_does_not_replace_visible_history(self):
        from langgraph.checkpoint.memory import InMemorySaver
        import server
        cid = self.create()
        graph = self.graph(InMemorySaver())
        expected = []
        with patch.object(server, 'get_web_agent', return_value=graph):
            for index in range(6):
                question = f'原始消息-{index}'
                self.send(cid, question)
                expected.extend([{'role': 'user', 'text': question},
                    {'role': 'assistant', 'text': '中文流式测试通过：' + question}])
            state = graph.get_state(server.conversation_config('AAA2509001', cid))
            self.assertTrue(any(m.additional_kwargs.get('lc_source') == 'summarization'
                                for m in state.values['messages']))
            self.assertEqual(self.detail(cid)['messages'], expected)
            self.assertEqual(self.detail(cid)['messages'], expected)
            denied = self.client.get('/api/conversations/' + cid, headers=self.bob)
            self.assertEqual(denied.status_code, 404)

    def test_completed_history_survives_checkpointer_reopen(self):
        from langgraph.checkpoint.sqlite import SqliteSaver
        import server
        cid = self.create()
        path = str(Path(self.tmp.name) / 'history-checkpoints.db')
        with SqliteSaver.from_conn_string(path) as saver:
            with patch.object(server, 'get_web_agent', return_value=self.graph(saver)):
                for index in range(4):
                    self.send(cid, f'重启前-{index}')
                expected = self.detail(cid)['messages']
                self.assertEqual(len(expected), 8)
        with SqliteSaver.from_conn_string(path) as saver:
            with patch.object(server, 'get_web_agent', return_value=self.graph(saver)):
                self.assertEqual(self.detail(cid)['messages'], expected)


if __name__ == '__main__':
    unittest.main()
