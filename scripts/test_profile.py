"""Complete profile reads through the real tool and offline memory stores."""
import json
import os
from pathlib import Path
import sys
import unittest

os.environ["CAMPUS_SKIP_DOTENV"] = "1"
os.environ["LANGSMITH_TRACING"] = "false"
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from langgraph.prebuilt import ToolRuntime
from langgraph.store.memory import InMemoryStore

from context import UserContext
from tools.profile import read_profile, save_profile


def runtime_for(store, user_id="profile-test-a"):
    return ToolRuntime(state={}, context=UserContext(user_id=user_id), config={},
                       stream_writer=lambda _: None, tool_call_id="profile-test", store=store)


class ProfileTest(unittest.TestCase):
    def test_complete_profile_includes_more_than_ten_fields(self):
        runtime = runtime_for(InMemoryStore())
        expected = {f"field-{i:03}": f"合成偏好-{i}" for i in range(12)}
        for key, value in expected.items():
            result = json.loads(save_profile.func(key=key, value=value, runtime=runtime))
            self.assertTrue(result["ok"])

        result = json.loads(read_profile.func(runtime=runtime))
        self.assertTrue(result["ok"])
        self.assertEqual(len(result["profile"]), len(expected),
                         "完整画像被默认的 10 条查询上限截断")
        self.assertEqual(result["profile"], expected)


if __name__ == "__main__":
    unittest.main()
