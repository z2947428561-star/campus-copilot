"""Single-process turn ownership and bounded delivery to an HTTP client."""
import asyncio
import queue
import threading


class RunRegistry:
    def __init__(self):
        self._active = set()
        self._guard = threading.Lock()

    def claim(self, thread_id):
        with self._guard:
            if thread_id in self._active:
                return False
            self._active.add(thread_id)
            return True

    def release(self, thread_id):
        with self._guard:
            self._active.discard(thread_id)

    def snapshot(self, thread_id, read):
        # Keep a worker from publishing "not running" between a checkpoint read
        # and its busy flag. Otherwise a refresh could miss its final reply.
        with self._guard:
            return read(), thread_id in self._active


class EventStream:
    """Disconnect stops delivery, not execution; the worker owns its run lock."""
    def __init__(self):
        self._queue = queue.Queue(maxsize=128)
        self._disconnected = threading.Event()
        self._end = object()

    def publish(self, event):
        while not self._disconnected.is_set():
            try:
                self._queue.put(event, timeout=0.2)
                return
            except queue.Full:
                pass

    def finish(self):
        self.publish(self._end)

    async def events(self):
        try:
            while True:
                try:
                    event = await asyncio.to_thread(self._queue.get, True, 0.5)
                except queue.Empty:
                    yield None  # heartbeat, also lets StreamingResponse notice disconnects
                    continue
                if event is self._end:
                    return
                yield event
        finally:
            self._disconnected.set()
