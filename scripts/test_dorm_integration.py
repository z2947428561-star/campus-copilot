"""Offline assertion, account isolation and service-only API regression checks."""
import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def assertion(secret, *, subject="7", now=None, **changes):
    now = int(time.time()) if now is None else now
    payload = dict(iss="xmumdorm", aud="campus-copilot", sub=subject, iat=now, exp=now + 60)
    payload.update(changes)
    encode = lambda data: base64.urlsafe_b64encode(json.dumps(data).encode()).rstrip(b"=").decode()
    unsigned = encode({"alg": "HS256", "typ": "JWT"}) + "." + encode(payload)
    signature = base64.urlsafe_b64encode(hmac.new(secret.encode(), unsigned.encode(), hashlib.sha256).digest()).rstrip(b"=").decode()
    return unsigned + "." + signature


class DormIntegrationTests(unittest.TestCase):
    def test_focused_answer_checks_detect_the_reported_noise(self):
        from eval_dorm_answers import style_checks
        concise = "未达到出勤要求且没有获准的例外，就不能参加期末考试。"
        self.assertTrue(all(style_checks(concise).values()))
        verbose = "我先检索资料。\n## 建议\ncollected_at=unknown。另有60%的规则。\n来源：[P-1234567890abcdef](https://www.xmu.edu.my/handbook.pdf)"
        checks = style_checks(verbose, forbidden=("60%",))
        for key in ("no_process_narration", "no_internal_metadata", "no_report_headings", "no_source_details", "no_unasked_topics"):
            self.assertFalse(checks[key], key)
        self.assertFalse(style_checks("来自学生手册：未达到要求不能参加考试。")["no_source_preamble"])
        self.assertFalse(style_checks("不能参加考试。生效日期尚未核实。")["no_appended_dates"])

    def test_live_verification_compares_the_whole_turn(self):
        from verify_dorm_live import reply_matches_history
        messages = [{"role": "user", "text": "earlier"}, {"role": "assistant", "text": "old reply"},
                    {"role": "user", "text": "new question"}, {"role": "assistant", "text": "checking sources"},
                    {"role": "assistant", "text": "final answer"}]
        self.assertTrue(reply_matches_history("checking sourcesfinal answer", messages))
        self.assertFalse(reply_matches_history("checking sourcesfinal answer", messages[:-1]))
        self.assertFalse(reply_matches_history("checking sourcesfinal answerunexpected", messages))

    def test_bridge(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {
            "CAMPUS_SKIP_DOTENV": "1", "MEMORY_BACKEND": "sqlite",
            "MEMORY_DB_PATH": str(Path(tmp) / "memory.db"), "LANGSMITH_TRACING": "false",
            "CAMPUS_AGENT_SHARED_SECRET": secrets.token_urlsafe(32),
        }):
            import config
            import dorm_auth
            import server
            import student_data
            from fastapi.testclient import TestClient
            from browser_fixtures import create_catalog
            from fake_chat_agent import BrowserTestModel, build_agent
            from agent import assistant, middleware
            from langchain_core.language_models.fake_chat_models import FakeListChatModel
            from prompts.system import build_dorm_system_prompt
            catalog = Path(tmp) / "campus.db"
            create_catalog(catalog)
            key = config.XMUMDORM_SHARED_SECRET
            self.assertEqual(dorm_auth.verify_assertion(assertion(key), now=time.time()), "xmumdorm:7")
            for changes in ({"exp": 0}, {"aud": "other"}, {"iss": "other"}, {"sub": "0"},
                            {"exp": int(time.time()) + 3600}, {"iat": True}):
                with self.subTest(changes=changes), self.assertRaises(ValueError):
                    dorm_auth.verify_assertion(assertion(key, **changes))
            with self.assertRaises(ValueError):
                dorm_auth.verify_assertion(assertion("wrong-key"))
            with patch.object(config, "XMUMDORM_SHARED_SECRET", ""):
                with self.assertRaises(RuntimeError): dorm_auth.verify_assertion("")
            prompt = build_dorm_system_prompt()
            self.assertIn("search_policy", prompt)
            self.assertNotIn("→calculate_gpa", prompt)
            with patch.object(assistant, "get_chat_model", return_value=BrowserTestModel()), \
                 patch.object(middleware, "get_cheap_model", return_value=FakeListChatModel(responses=["summary"])), \
                 patch.object(middleware, "get_fallback_middleware", return_value=None):
                restricted = server.agent_for_user("xmumdorm:7")
                tool_node = restricted.get_graph().nodes["tools"].data
                self.assertEqual(set(tool_node.tools_by_name), {"search_policy", "search_guides", "get_my_schedule", "get_my_todos", "get_my_campus_clock", "get_campus_holidays"})
            with patch.object(student_data, "CATALOG_DB", catalog), TestClient(server.app) as client:
                server._dorm_agent = build_agent()
                prefix = "/internal/xmumdorm"
                headers = {"X-Campus-Assertion": assertion(key)}
                self.assertEqual(client.get(prefix + "/conversations").status_code, 401)
                self.assertEqual(client.get("/api/conversations", headers=headers).status_code, 401)
                self.assertEqual(client.get(prefix + "/database", headers=headers).status_code, 404)
                created = client.post(prefix + "/conversations", headers=headers).json()
                url = prefix + "/conversations/" + created["id"]
                other = {"X-Campus-Assertion": assertion(key, subject="8")}
                self.assertEqual(client.get(url, headers=other).status_code, 404)
                reply = client.post(prefix + "/chat", headers=headers,
                                    json={"message": "hello", "conversation_id": created["id"]})
                self.assertEqual(reply.status_code, 200)
                self.assertIn("text/event-stream", reply.headers["content-type"])
                self.assertIn('"type": "done"', reply.text)
                saved = client.get(url, headers=headers).json()
                self.assertTrue(any(m["role"] == "user" and m["text"] == "hello" for m in saved["messages"]))
                self.assertFalse(saved["running"])
                self.assertEqual(client.post(prefix + "/chat", headers=headers, json={"message": "x" * 4001}).status_code, 422)
                self.assertEqual(client.delete(url, headers=other).status_code, 404)
                self.assertEqual(client.post(url + '/restore', headers=other).status_code, 404)
                self.assertEqual(client.delete(url).status_code, 401)
                thread_id = server.conversations.thread_id_for('xmumdorm:7', created['id'])
                self.assertTrue(server._runs.claim(thread_id))
                try:
                    self.assertEqual(client.delete(url, headers=headers).status_code, 409)
                finally:
                    server._runs.release(thread_id)
                self.assertEqual(client.delete(url, headers=headers).status_code, 200)
                self.assertNotIn(created['id'], [item['id'] for item in client.get(prefix + '/conversations', headers=headers).json()['conversations']])
                self.assertEqual(client.get(url, headers=headers).status_code, 404)
                self.assertEqual(client.post(prefix + '/chat', headers=headers, json={'message': 'hidden', 'conversation_id': created['id']}).status_code, 404)
                self.assertEqual(client.post(url + '/restore', headers=headers).status_code, 200)
                restored = client.get(url, headers=headers).json()
                self.assertEqual(restored['messages'], saved['messages'])
                claim = server._runs.claim
                def delete_before_claim(thread):
                    server.conversations.delete_conversation('xmumdorm:7', created['id'])
                    return claim(thread)
                with patch.object(server._runs, 'claim', side_effect=delete_before_claim), patch.object(server, 'agent_for_user') as model:
                    raced = client.post(prefix + '/chat', headers=headers, json={'message': 'race', 'conversation_id': created['id']})
                    self.assertEqual(raced.status_code, 404)
                    model.assert_not_called()
                self.assertTrue(server._runs.claim(thread_id))
                server._runs.release(thread_id)
                self.assertEqual(client.post(url + '/restore', headers=headers).status_code, 200)
                legacy_url = prefix + '/conversations/main'
                self.assertEqual(client.delete(legacy_url, headers=headers).status_code, 200)
                server.conversations.init_conversations()
                for _ in range(2):
                    self.assertNotIn('main', [item['id'] for item in client.get(prefix + '/conversations', headers=headers).json()['conversations']])
                    self.assertEqual(client.get(legacy_url, headers=headers).status_code, 404)
                self.assertEqual(client.post(legacy_url + '/restore', headers=headers).status_code, 200)
                self.assertIn('main', [item['id'] for item in client.get(prefix + '/conversations', headers=headers).json()['conversations']])


if __name__ == "__main__":
    unittest.main()
