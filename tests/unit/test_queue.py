"""Cancellation does not start a second model while the first thread runs."""

import asyncio
import threading

from backend.app.runtime.inference_queue import InferenceQueue


def test_serial_worker_cooperative_cancel_and_capacity():
    async def run():
        started, release = threading.Event(), threading.Event()
        order = []

        class Events:
            evicted = False

            def append(self, *args):
                if self.evicted:
                    raise KeyError("History evicted")

        class Runner:
            def run(self, identifier, request, context):
                if identifier == "first":
                    started.set()
                    assert release.wait(5)
                context.check()
                order.append(identifier)

        events = Events()
        queue = InferenceQueue(Runner(), events, 30, 1)
        await queue.start()
        await queue.submit("first", None)
        assert await asyncio.to_thread(started.wait, 5)
        await queue.submit("second", None)
        try:
            await queue.submit("third", None)
            raise AssertionError("Queue capacity must be enforced")
        except RuntimeError:
            pass
        queue.cancel("first")
        events.evicted = True
        assert not order
        release.set()
        await asyncio.wait_for(queue.queue.join(), 5)
        assert order == ["second"]
        await queue.stop()

    asyncio.run(run())
