"""Application-wide, bounded task scheduling for single and batch grading."""

import asyncio
import logging

from .agent import AgentRunner
from .rubric import VERSION
from .storage import Store


logger = logging.getLogger(__name__)


class BatchRunner:
    def __init__(self, store: Store, agent_runner: AgentRunner, concurrency: int = 3):
        if type(concurrency) is not int or concurrency < 1:
            raise ValueError("并发数必须为正整数")
        self.store = store
        self.runner = agent_runner
        self.semaphore = asyncio.Semaphore(concurrency)
        self._active: set[asyncio.Task] = set()
        self._task_ids: set[str] = set()
        self._batch_ids: set[str] = set()
        self._closing = False

    def _fail_unfinished(self, task_id: str, code: str):
        task = self.store.get_task(task_id)
        if task["rubric_version"] != VERSION or task["status"] not in ("queued", "running"):
            return
        message = (
            "任务运行中断，请重试或人工批改。"
            if code == "interrupted"
            else "任务调度异常，请重试或人工批改。"
        )
        self.runner.fail(task_id, code, message)

    def _refresh(self, batch_id: str | None):
        if batch_id:
            self.store.update_batch_progress(batch_id)

    async def run_task(self, task_id: str):
        """All HTTP grading entry points share this semaphore and task deduplication."""
        if task_id in self._task_ids:
            return
        current = asyncio.current_task()
        self._active.add(current)
        self._task_ids.add(task_id)
        batch_id = None
        try:
            task = self.store.get_task(task_id)
            batch_id = task.get("batch_id")
            if task["rubric_version"] != VERSION or task["status"] != "queued":
                return
            if self._closing:
                self._fail_unfinished(task_id, "interrupted")
                return
            async with self.semaphore:
                if self._closing:
                    self._fail_unfinished(task_id, "interrupted")
                    return
                await self.runner.run(task_id)
        except asyncio.CancelledError:
            self._fail_unfinished(task_id, "interrupted")
            raise
        except Exception:
            # Do not publish arbitrary provider exceptions or credentials.
            logger.warning("任务 %s 调度失败", task_id)
            self._fail_unfinished(task_id, "execution_error")
        finally:
            try:
                self._refresh(batch_id)
            finally:
                self._task_ids.discard(task_id)
                self._active.discard(current)

    async def run_batch(self, batch_id: str):
        if batch_id in self._batch_ids:
            return
        current = asyncio.current_task()
        self._active.add(current)
        self._batch_ids.add(batch_id)
        tasks = []
        try:
            tasks = self.store.get_batch_tasks(batch_id)
            if self._closing:
                for task in tasks:
                    self._fail_unfinished(task["id"], "interrupted")
                return
            await asyncio.gather(*(
                self.run_task(task["id"])
                for task in tasks
                if task["status"] == "queued" and task["rubric_version"] == VERSION
            ))
        except asyncio.CancelledError:
            # Include children cancelled before their coroutine first started.
            for task in tasks:
                self._fail_unfinished(task["id"], "interrupted")
            raise
        finally:
            try:
                self._refresh(batch_id)
            finally:
                self._batch_ids.discard(batch_id)
                self._active.discard(current)

    async def aclose(self):
        """Finish cancellation writes before the lifespan closes the database."""
        self._closing = True
        current = asyncio.current_task()
        active = [task for task in self._active if task is not current]
        for task in active:
            task.cancel()
        if active:
            await asyncio.gather(*active, return_exceptions=True)
