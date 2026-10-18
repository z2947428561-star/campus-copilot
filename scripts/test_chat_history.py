"""User-visible history must survive real context summarization and resume."""
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

    def graph(self, saver, *, summary=True, hitl=False, pii=False):
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
        if pii:
            from agent.middleware import get_pii_middleware
            middleware.insert(0, get_pii_middleware())
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

    def test_legacy_checkpoints_backfill_originals_and_skip_summaries(self):
        from langgraph.checkpoint.memory import InMemorySaver
        from langchain_core.messages import HumanMessage
        from context import UserContext
        import server
        cid = self.create()
        graph = self.graph(InMemorySaver())
        cfg = server.conversation_config('AAA2509001', cid)
        for index in range(5):
            graph.invoke({'messages': [HumanMessage(f'旧版-{index}')]}, cfg,
                         context=UserContext(user_id='AAA2509001', semester_id='2026-09'))
        self.assertTrue(any(m.additional_kwargs.get('lc_source') == 'summarization'
                            for m in graph.get_state(cfg).values['messages']))
        with patch.object(server, 'get_web_agent', return_value=graph):
            messages = self.detail(cid)['messages']
            self.assertEqual(len(messages), 10)
            self.assertEqual([m['text'] for m in messages if m['role'] == 'user'], [f'旧版-{i}' for i in range(5)])
            self.assertFalse(any('synthetic-summary' in m['text'] for m in messages))
            self.assertEqual(self.detail(cid)['messages'], messages)

    def test_approval_resume_does_not_duplicate_user_or_model_messages(self):
        from langgraph.checkpoint.memory import InMemorySaver
        import server
        cid = self.create()
        graph = self.graph(InMemorySaver(), summary=False, hitl=True)
        with patch.object(server, 'get_web_agent', return_value=graph):
            self.send(cid, '确认 GPA')
            pending = self.detail(cid)
            self.assertEqual(pending['messages'], [{'role': 'user', 'text': '确认 GPA'}])
            for decision, status in [('approve', 200), ('approve', 409)]:
                response = self.client.post('/api/chat', headers=self.alice, json={
                    'conversation_id': cid, 'checkpoint_id': pending['checkpoint_id'],
                    'decisions': [{'type': decision}]})
                self.assertEqual(response.status_code, status, response.text)
            expected = [{'role': 'user', 'text': '确认 GPA'}, {'role': 'assistant', 'text': '已确认测试操作'}]
            self.assertEqual(self.detail(cid)['messages'], expected)
            self.assertEqual(self.detail(cid)['messages'], expected)

    def test_original_input_is_preserved_when_model_context_is_redacted(self):
        from langgraph.checkpoint.memory import InMemorySaver
        import server
        cid = self.create()
        graph = self.graph(InMemorySaver(), summary=False, pii=True)
        question = '我的电话是 13800138000'
        with patch.object(server, 'get_web_agent', return_value=graph):
            self.send(cid, question)
            messages = self.detail(cid)['messages']
            self.assertEqual(messages[0], {'role': 'user', 'text': question})
            self.assertNotIn('13800138000', messages[1]['text'])

    def test_partial_output_survives_stream_error_without_duplication(self):
        import server
        from test_conversations import fake_agent
        cid = self.create()

        def fail(*args, **kwargs):
            kwargs['on_token']('已经显示的部分回复')
            raise RuntimeError('synthetic failure')

        with patch.object(server, 'get_web_agent', return_value=fake_agent()), \
             patch.object(server, 'stream_turn', side_effect=fail):
            response = self.client.post('/api/chat', headers=self.alice,
                json={'conversation_id': cid, 'message': '失败案例'})
            self.assertIn('"type": "error"', response.text)
            expected = [{'role': 'user', 'text': '失败案例'}, {'role': 'assistant', 'text': '已经显示的部分回复'}]
            self.assertEqual(self.detail(cid)['messages'], expected)
            self.assertEqual(self.detail(cid)['messages'], expected)

    def test_postgres_capture_uses_cursor_parameters_and_closes_cursor(self):
        from unittest.mock import MagicMock
        from langchain_core.messages import HumanMessage
        import chat_history
        connection = MagicMock()
        cursor = connection.cursor.return_value
        with patch.object(chat_history, 'personal_connection') as factory, \
             patch.object(chat_history, 'placeholder', return_value='%s'):
            factory.return_value.__enter__.return_value = connection
            chat_history.capture('owner', 'thread', [HumanMessage('synthetic', id='message-1')], '2026-09')
        sql, parameters = cursor.executemany.call_args.args
        self.assertEqual(sql.count('%s'), 7)
        self.assertEqual(parameters[0][:6], ('owner', 'thread', 'message-1', 'user', 'synthetic', '2026-09'))
        cursor.close.assert_called_once()


if __name__ == '__main__':
    unittest.main()
