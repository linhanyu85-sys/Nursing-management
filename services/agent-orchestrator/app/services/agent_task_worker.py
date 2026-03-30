from __future__ import annotations

import asyncio

from app.core.config import settings
from app.services.agent_queue_store import AgentQueueStore, agent_queue_store
from app.services.agent_runtime import AgentRuntime, runtime


class AgentTaskWorker:
    def __init__(
        self,
        *,
        qs: AgentQueueStore | None = None,
        rt: AgentRuntime | None = None,
    ) -> None:
        self._qs = qs or agent_queue_store
        self._rt = rt or runtime
        self._task: asyncio.Task[None] | None = None
        self._stop_ev: asyncio.Event | None = None
        self._wake_ev: asyncio.Event | None = None
        self._recovered = 0

    async def start(self) -> None:
        if not settings.agent_queue_worker_enabled:
            return
        if self._task and not self._task.done():
            return
        self._stop_ev = asyncio.Event()
        self._wake_ev = asyncio.Event()
        self._recovered = self._qs.recover_incomplete_tasks()
        self.notify()
        self._task = asyncio.create_task(self._loop(), name="agent-task-worker")

    async def stop(self) -> None:
        if not self._task:
            return
        if self._stop_ev:
            self._stop_ev.set()
        self.notify()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None

    def notify(self) -> None:
        if self._wake_ev:
            self._wake_ev.set()

    def status(self) -> dict[str, int | bool]:
        return {
            "worker_enabled": settings.agent_queue_worker_enabled,
            "worker_running": bool(self._task and not self._task.done()),
            "recovered_tasks": self._recovered,
            **self._qs.stats(),
        }

    async def _loop(self) -> None:
        assert self._stop_ev is not None
        assert self._wake_ev is not None

        while not self._stop_ev.is_set():
            try:
                t = self._qs.claim_next()
                if t is None:
                    try:
                        sec = max(float(settings.agent_queue_poll_interval_sec), 0.2)
                        await asyncio.wait_for(self._wake_ev.wait(), timeout=sec)
                    except asyncio.TimeoutError:
                        pass
                    finally:
                        self._wake_ev.clear()
                    continue
                await self._process(t.id)
            except Exception:
                await asyncio.sleep(max(float(settings.agent_queue_poll_interval_sec), 0.2))

    async def _process(self, tid: str) -> None:
        t = self._qs.get(tid)
        if t is None:
            return
        try:
            out = await self._rt.run(
                t.payload.model_copy(deep=True),
                engine_override=t.requested_engine,
            )
        except Exception as exc:
            self._qs.fail(tid, error=str(exc) or exc.__class__.__name__)
            return

        if out.pending_approvals:
            self._qs.wait_for_approval(tid, out)
            return
        self._qs.complete(tid, out)


agent_task_worker = AgentTaskWorker()
