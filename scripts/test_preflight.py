"""预检脚本的离线单元测试。"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from preflight import check_environment


class PreflightTest(unittest.TestCase):
    def test_missing_configuration_is_rejected(self):
        errors = check_environment({})
        self.assertTrue(any("POSTGRES_PASSWORD" in item for item in errors))
        self.assertTrue(any("CAMPUS_DOMAIN" in item for item in errors))

    def test_valid_configuration(self):
        values = {
            "DEEPSEEK_API_KEY": "sk-test-only",
            "EMBED_API_KEY": "sk-test-only",
            "POSTGRES_PASSWORD": "Abcdefghijklmnop12345678",
            "CAMPUS_DOMAIN": "chat.example.com",
            "LANGSMITH_TRACING": "false",
            "KB_BACKEND": "milvus",
        }
        self.assertEqual(check_environment(values), [])


if __name__ == "__main__":
    unittest.main()
