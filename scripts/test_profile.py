"""Complete profile reads through the real tool and offline memory stores."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

os.environ["CAMPUS_SKIP_DOTENV"] = "1"
os.environ["LANGSMITH_TRACING"] = "false"
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from langgraph.prebuilt import ToolRuntime
from langgraph.store.memory import InMemoryStore
from langgraph.store.sqlite import SqliteStore

from context import UserContext
from tools.profile import read_profile, save_profile


def runtime_for(store, user_id="profile-test-a"):
    return ToolRuntime(state={}, context=UserContext(user_id=user_id), config={},
                       stream_writer=lambda _: None, tool_call_id="profile-test", store=store)


@contextmanager
def memory_store(backend):
    if backend == "memory":
        yield InMemoryStore()
    else:
        with SqliteStore.from_conn_string(":memory:") as store:
            store.setup()
            yield store


class ProfileTest(unittest.TestCase):
    def write_fields(self, runtime, count):
        expected = {f"field-{i:03}": f"合成偏好-{i}" for i in range(count)}
        for key, value in expected.items():
            result = json.loads(save_profile.func(key=key, value=value, runtime=runtime))
            self.assertTrue(result["ok"])
        return expected

    def read_fields(self, runtime):
        result = json.loads(read_profile.func(runtime=runtime))
        self.assertTrue(result["ok"])
        self.assertEqual(result["user"], runtime.context.user_id)
        return result["profile"]

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

    def test_complete_profile_across_page_boundaries_on_real_stores(self):
        for backend in ("memory", "sqlite"):
            for count in (0, 1, 10, 11, 99, 100, 101, 200, 205):
                with self.subTest(backend=backend, fields=count), memory_store(backend) as store:
                    runtime = runtime_for(store)
                    expected = self.write_fields(runtime, count)
                    self.assertEqual(self.read_fields(runtime), expected)

    def test_pagination_keeps_accounts_and_namespaces_isolated(self):
        for backend in ("memory", "sqlite"):
            with self.subTest(backend=backend), memory_store(backend) as store:
                alice = runtime_for(store)
                expected = self.write_fields(alice, 205)
                for user in ("profile-test-b", "profile-test-a-extra"):
                    bob = runtime_for(store, user)
                    save_profile.func(key="field-000", value=f"仅属于 {user}", runtime=bob)
                    save_profile.func(key="other-only", value="其他用户字段", runtime=bob)
                store.put(("other", alice.context.user_id), "outside", {"value": "其他命名空间"})
                self.assertEqual(self.read_fields(alice), expected)
                for user in ("profile-test-b", "profile-test-a-extra"):
                    self.assertEqual(self.read_fields(runtime_for(store, user)), {
                        "field-000": f"仅属于 {user}", "other-only": "其他用户字段"})

    def test_sqlite_reopen_returns_all_fields_and_latest_updates(self):
        with tempfile.TemporaryDirectory(prefix="campus-profile-") as tmp:
            path = str(Path(tmp) / "profiles.db")
            with SqliteStore.from_conn_string(path) as store:
                store.setup()
                runtime = runtime_for(store)
                expected = self.write_fields(runtime, 205)
                for key in ("field-000", "field-100", "field-204"):
                    value = "更新后的合成偏好"
                    save_profile.func(key=key, value=value, runtime=runtime)
                    expected[key] = value
            with SqliteStore.from_conn_string(path) as store:
                self.assertEqual(self.read_fields(runtime_for(store)), expected)

    def test_later_page_failure_cannot_return_a_successful_partial_profile(self):
        store = InMemoryStore()
        runtime = runtime_for(store)
        self.write_fields(runtime, 205)
        search = store.search

        def fail_later(_store, namespace, **kwargs):
            if kwargs.get("offset", 0):
                raise OSError("synthetic later-page failure")
            return search(namespace, **kwargs)

        with patch.object(InMemoryStore, "search", autospec=True, side_effect=fail_later):
            with self.assertRaisesRegex(OSError, "later-page failure"):
                read_profile.func(runtime=runtime)

    def test_missing_store_or_identity_is_rejected_before_access(self):
        result = json.loads(read_profile.func(runtime=runtime_for(None)))
        self.assertFalse(result["ok"])
        store = InMemoryStore()
        for user_id in (None, "", " \t"):
            with self.subTest(user_id=user_id):
                runtime = runtime_for(store, user_id or "unused")
                runtime.context = None if user_id is None else UserContext(user_id=user_id)
                with (
                    patch.object(InMemoryStore, "search", autospec=True) as search,
                    patch.object(InMemoryStore, "put", autospec=True) as put,
                ):
                    self.assertFalse(json.loads(read_profile.func(runtime=runtime))["ok"])
                    self.assertFalse(json.loads(save_profile.func(
                        key="field", value="synthetic", runtime=runtime))["ok"])
                    search.assert_not_called()
                    put.assert_not_called()


if __name__ == "__main__":
    unittest.main()
