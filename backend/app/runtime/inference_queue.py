"""One serial CPU inference worker with cooperative cancellation/deadlines."""

import asyncio
import threading
import time
from dataclasses import dataclass, field


class AnalysisAborted(RuntimeError):
    pass


@dataclass
class AnalysisContext:
    deadline: float
    cancelled: threading.Event = field(default_factory=threading.Event)

    def check(self):
        if self.cancelled.is_set():
            raise AnalysisAborted("cancelled")
        if time.monotonic() >= self.deadline:
            raise AnalysisAborted("deadline_exceeded")


class InferenceQueue:
    def __init__(self, runner, events, timeout, capacity):
        self.runner, self.events, self.timeout = runner, events, timeout
        self.queue = asyncio.Queue(maxsize=capacity)
        self.contexts = {}
        self.worker = None

    async def start(self):
        self.worker = asyncio.create_task(self._work())

    async def submit(self, identifier, request):
        context = AnalysisContext(time.monotonic() + self.timeout)
        self.contexts[identifier] = context
        try:
            self.queue.put_nowait((identifier, request, context))
        except asyncio.QueueFull:
            del self.contexts[identifier]
            raise RuntimeError("Inference queue is full") from None

    def cancel(self, identifier):
        if identifier in self.contexts:
            self.contexts[identifier].cancelled.set()
        self.events.append(
            identifier, "analysis.error", {"code": "cancelled", "message": "Analysis cancelled"}
        )

    async def _work(self):
        while True:
            identifier, request, context = await self.queue.get()
            try:
                # Await the actual thread, even after cancellation. Do not let
                # the next request race models still executing in that thread.
                await asyncio.to_thread(self.runner.run, identifier, request, context)
            except Exception:
                try:
                    self.events.append(
                        identifier,
                        "analysis.error",
                        {"code": "engine_failed", "message": "Analysis could not complete"},
                    )
                except (KeyError, RuntimeError):
                    # Cancelled history may be evicted before a model returns.
                    # A lost record must not kill the only queue worker.
                    pass
            finally:
                self.contexts.pop(identifier, None)
                self.queue.task_done()

    async def stop(self):
        for context in self.contexts.values():
            context.cancelled.set()
        # Let a current synchronous model call finish before releasing models.
        await self.queue.join()
        if self.worker:
            self.worker.cancel()
            try:
                await self.worker
            except asyncio.CancelledError:
                pass
