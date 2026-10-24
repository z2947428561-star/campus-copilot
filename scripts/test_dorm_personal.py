"""Read-only personal tool identity, fixed transport and schema regressions."""
import io
import json
import os
from pathlib import Path
from types import SimpleNamespace
import sys
import unittest
from unittest.mock import patch

os.environ['CAMPUS_SKIP_DOTENV'] = '1'
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import config
import dorm_auth
import dorm_personal
from context import UserContext
from tools.dorm_personal import get_my_schedule, get_my_todos, get_my_campus_clock, get_campus_holidays, ScheduleInput, TodoInput, HolidayInput


class PersonalToolsTest(unittest.TestCase):
    def setUp(self):
        self.secret = patch.object(config, 'XMUMDORM_SHARED_SECRET', 'test-personal-callback-key-at-least-32-characters')
        self.url = patch.object(config, 'XMUMDORM_API_URL', 'http://127.0.0.1:4040')
        self.secret.start(); self.url.start()
        self.runtime = SimpleNamespace(context=UserContext(user_id='xmumdorm:7'))

    def tearDown(self):
        self.secret.stop(); self.url.stop()

    def test_reverse_assertion_cannot_be_used_as_forward_identity(self):
        token = dorm_personal.assertion('xmumdorm:7')
        with self.assertRaises(ValueError): dorm_auth.verify_assertion(token)
        for identity in ['native-user', 'xmumdorm:0', 'xmumdorm:07', '', None]:
            with self.assertRaises(ValueError): dorm_personal.assertion(identity)

    def test_fixed_callback_keeps_identity_out_of_query_and_returns_data(self):
        seen = []
        class Opener:
            def open(inner, request, timeout):
                seen.append(request)
                return io.BytesIO(json.dumps({'status': 0, 'data': {'items': [], 'total': 0}}).encode())
        result = dorm_personal.read_personal('todos', {'when': 'today'}, self.runtime, opener=Opener())
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(seen[0].full_url, 'http://127.0.0.1:4040/internal/campus-agent/personal/todos?when=today')
        self.assertEqual(seen[0].get_method(), 'GET')
        self.assertTrue(seen[0].get_header('X-campus-agent-assertion'))
        self.assertNotIn('xmumdorm', seen[0].full_url.split('?')[-1])

    def test_missing_identity_or_insecure_callback_never_sends_request(self):
        opener = SimpleNamespace(open=lambda *args, **kwargs: self.fail('Unexpected network call'))
        result = dorm_personal.read_personal('todos', {}, None, opener=opener)
        self.assertEqual(result['status'], 'unavailable')
        for url in ['http://remote.example', 'https://user:password@example.com', 'https://example.com/other']:
            with patch.object(config, 'XMUMDORM_API_URL', url):
                self.assertEqual(dorm_personal.read_personal('schedule', {}, self.runtime, opener=opener)['status'], 'unavailable')

    def test_redirects_and_driver_details_are_not_returned(self):
        class Broken:
            def open(inner, *args, **kwargs):
                raise RuntimeError('private token mysql://secret')
        result = dorm_personal.read_personal('todos', {}, self.runtime, opener=Broken())
        self.assertEqual(result, {'status': 'unavailable', 'reason': 'personal_query_failed'})
        self.assertIsNone(dorm_personal.NoRedirect().redirect_request(None, None, 302, '', {}, 'https://elsewhere.example'))

    def test_tools_have_no_identity_url_or_write_parameters(self):
        for tool in [get_my_schedule, get_my_todos, get_my_campus_clock, get_campus_holidays]:
            properties = tool.tool_call_schema.model_json_schema().get('properties', {})
            self.assertFalse({'runtime', 'user_id', 'token', 'url'} & properties.keys())
        with self.assertRaises(ValueError): ScheduleInput(user_id=8)
        with self.assertRaises(ValueError): TodoInput(user_id=8)
        with self.assertRaises(ValueError): HolidayInput(user_id=8)
        with patch('tools.dorm_personal.read_personal', return_value={'status': 'ok', 'data': {}}) as read:
            get_my_schedule.func(when='next_week', weekday=1, runtime=self.runtime)
            self.assertEqual(read.call_args.args[:2], ('schedule', {'when': 'next_week', 'weekday': 1}))
            get_my_todos.func(when='tomorrow', runtime=self.runtime)
            self.assertEqual(read.call_args.args[1], {'when': 'tomorrow', 'status': 'active', 'page': 1})
            get_campus_holidays.func(when='year', year=2027, name='圣诞节', runtime=self.runtime)
            self.assertEqual(read.call_args.args[:2], ('holidays', {'when': 'year', 'year': 2027, 'name': '圣诞节'}))

    def test_graph_injects_the_verified_runtime_into_personal_tools(self):
        from langchain.agents import create_agent
        from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
        from langchain_core.messages import AIMessage, HumanMessage
        class Model(FakeMessagesListChatModel):
            def bind_tools(self, tools, **kwargs): return self
        model = Model(responses=[AIMessage(content='', tool_calls=[{
            'id': 'call-personal', 'name': 'get_my_schedule', 'args': {
                'when': 'next_week', 'weekday': 1,
                'runtime': {'context': {'user_id': 'xmumdorm:8'}}}}]), AIMessage(content='done')])
        with patch('tools.dorm_personal.read_personal', return_value={'status': 'ok', 'data': {}}) as read:
            graph = create_agent(model=model, tools=[get_my_schedule], context_schema=UserContext)
            result = graph.invoke({'messages': [HumanMessage('test')]}, context=UserContext('xmumdorm:7'))
            errors = [str(message.content)[:120] for message in result['messages'] if getattr(message, 'type', None) == 'tool' and getattr(message, 'status', '') == 'error']
            self.assertEqual(read.call_count, 1, errors)
            self.assertEqual(read.call_args.args[2].context.user_id, 'xmumdorm:7')


if __name__ == '__main__':
    unittest.main()
