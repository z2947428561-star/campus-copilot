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

    def test_same_conversation_finish_waits_for_snapshot_consistency(self):
        registry = RunRegistry()
        registry.claim('same')
        reading, finishing, unblock, finished = (threading.Event() for _ in range(4))

        def read():
            reading.set()
            if not unblock.wait(5):
                raise TimeoutError('snapshot not released')
            return 'snapshot while running'

        def finish():
            finishing.set()
            registry.release('same')
            finished.set()

        with ThreadPoolExecutor(max_workers=2) as pool:
            snapshot = pool.submit(registry.snapshot, 'same', read)
            try:
                self.assertTrue(reading.wait(2))
                worker = pool.submit(finish)
                self.assertTrue(finishing.wait(2))
                self.assertFalse(finished.wait(.1), 'Finish overtook an in-flight snapshot')
            finally:
                unblock.set()
            self.assertEqual(snapshot.result(timeout=2), ('snapshot while running', True))
            worker.result(timeout=2)
        self.assertEqual(registry.snapshot('same', lambda: 'final'), ('final', False))

    def test_start_cannot_overtake_an_idle_snapshot_of_same_conversation(self):
        registry = RunRegistry()
        reading, attempting, unblock, started = (threading.Event() for _ in range(4))

        def read():
            reading.set()
            if not unblock.wait(5):
                raise TimeoutError('snapshot not released')
            return 'idle snapshot'

        def start():
            attempting.set()
            result = registry.claim('same')
            started.set()
            return result

        with ThreadPoolExecutor(max_workers=2) as pool:
            snapshot = pool.submit(registry.snapshot, 'same', read)
            try:
                self.assertTrue(reading.wait(2))
                worker = pool.submit(start)
                self.assertTrue(attempting.wait(2))
                self.assertFalse(started.wait(.1), 'Start overtook an idle snapshot')
            finally:
                unblock.set()
            self.assertEqual(snapshot.result(timeout=2), ('idle snapshot', False))
            self.assertTrue(worker.result(timeout=2))
        self.assertFalse(registry.claim('same'))
        registry.release('same')

    def test_concurrent_claims_have_exactly_one_owner_and_can_reuse_id(self):
        registry = RunRegistry()
        with ThreadPoolExecutor(max_workers=12) as pool:
            for _ in range(20):
                barrier = threading.Barrier(12)

                def claim():
                    barrier.wait(timeout=3)
                    return registry.claim('same')

                results = list(pool.map(lambda _: claim(), range(12)))
                self.assertEqual(sum(results), 1)
                registry.release('same')
        self.assertTrue(registry.claim('same'))

    def test_read_exception_releases_coordination_but_preserves_owner(self):
        registry = RunRegistry()
        registry.claim('same')

        def fail():
            raise RuntimeError('synthetic read failure')

        with self.assertRaisesRegex(RuntimeError, 'synthetic'):
            registry.snapshot('same', fail)
        with ThreadPoolExecutor(max_workers=1) as pool:
            state = pool.submit(registry.snapshot, 'same', lambda: 'recovered').result(timeout=2)
            self.assertEqual(state, ('recovered', True))
            self.assertFalse(pool.submit(registry.claim, 'same').result(timeout=2))
            pool.submit(registry.release, 'same').result(timeout=2)
            self.assertTrue(pool.submit(registry.claim, 'other').result(timeout=2))
        self.assertEqual(registry.snapshot('same', lambda: 'idle'), ('idle', False))


if __name__ == '__main__':
    unittest.main()
