"""Conversation coordination: blocked reads must remain local to one thread ID."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from agent.web_runs import RunRegistry


class RunRegistryTest(unittest.TestCase):
    def test_blocked_snapshot_does_not_block_other_conversation_operations(self):
        registry = RunRegistry()
        self.assertTrue(registry.claim('A'))
        self.assertTrue(registry.claim('B'))
        reading, unblock, progressed = threading.Event(), threading.Event(), threading.Event()

        def slow_read():
            reading.set()
            if not unblock.wait(5):
                raise TimeoutError('synthetic slow read not released')
            return 'A snapshot'

        def other_conversation():
            registry.release('B')
            self.assertTrue(registry.claim('B'))
            self.assertEqual(registry.snapshot('B', lambda: 'B snapshot'), ('B snapshot', True))
            registry.release('B')
            self.assertEqual(registry.snapshot('B', lambda: 'B finished'), ('B finished', False))
            progressed.set()

        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(registry.snapshot, 'A', slow_read)
            try:
                self.assertTrue(reading.wait(2))
                second = pool.submit(other_conversation)
                self.assertTrue(progressed.wait(1), 'Conversation B was blocked by conversation A snapshot I/O')
                second.result(timeout=1)
            finally:
                unblock.set()
            self.assertEqual(first.result(timeout=2), ('A snapshot', True))


if __name__ == '__main__':
    unittest.main()
