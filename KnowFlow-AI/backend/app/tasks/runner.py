"""后台任务执行器：并发受控、进度可订阅。"""

from __future__ import annotations

import asyncio
import logging

from app.core.config import get_settings

logger = logging.getLogger(__name__)


class TaskRunner:
    def __init__(self) -> None:
        self._subscribers: dict[str, set[asyncio.Queue]] = {}
        self._jobs: set[asyncio.Task] = set()
        self._semaphore: asyncio.Semaphore | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._semaphore = asyncio.Semaphore(max(1, get_settings().max_concurrent_tasks))

    def submit(self, task_id: str, document_id: str) -> None:
        """可从同步接口（线程池）调用，任务会被调度回事件循环。"""
        if self._loop is None:
            raise RuntimeError("任务执行器尚未启动")
        self._loop.call_soon_threadsafe(self._spawn, task_id, document_id)

    def _spawn(self, task_id: str, document_id: str) -> None:
        job = asyncio.create_task(self._run(task_id, document_id))
        self._jobs.add(job)
        job.add_done_callback(self._jobs.discard)

    async def _run(self, task_id: str, document_id: str) -> None:
        from app.services.pipeline import run_pipeline

        semaphore = self._semaphore or asyncio.Semaphore(1)
        async with semaphore:
            try:
                await run_pipeline(task_id, document_id)
            except Exception:  # noqa: BLE001
                logger.exception("后台任务异常：task=%s", task_id)

    # ---------- 进度订阅 ----------
    def subscribe(self, task_id: str) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=200)
        self._subscribers.setdefault(task_id, set()).add(queue)
        return queue

    def unsubscribe(self, task_id: str, queue: asyncio.Queue) -> None:
        subscribers = self._subscribers.get(task_id)
        if subscribers and queue in subscribers:
            subscribers.remove(queue)
        if subscribers is not None and not subscribers:
            self._subscribers.pop(task_id, None)

    def publish(self, event: dict) -> None:
        task_id = event.get("task_id")
        if not task_id:
            return
        for queue in list(self._subscribers.get(task_id, ())):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                logger.warning("SSE 订阅队列已满，丢弃事件：%s", task_id)

    async def shutdown(self) -> None:
        for job in list(self._jobs):
            job.cancel()
        self._jobs.clear()


runner = TaskRunner()
