"""Queue boundary used by the HTTP layer."""
from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from threading import Lock
from typing import Callable, Protocol
from src.orchestration.run_control import run_control



class InProcessJobRunner:
    """Development adapter. Results remain durable because tasks write to the database."""

    def __init__(self, max_workers: int = 2, timeout_seconds: float = 1800):
        self.executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="analysis-job")
        self.futures: dict[str, Future[None]] = {}
        self.lock = Lock()
        self.timeout_seconds = timeout_seconds

    def _run_controlled(self, run_id: str, task: Callable[[], None]) -> None:
        run_control.begin(run_id, self.timeout_seconds)
        try:
            task()
        finally:
            run_control.finish(run_id)

    def submit(self, run_id: str, task: Callable[[], None]) -> None:
        with self.lock:
            existing = self.futures.get(run_id)
            if existing and not existing.done():
                return
            self.futures[run_id] = self.executor.submit(self._run_controlled, run_id, task)

    def get_status(self, run_id: str) -> str | None:
        with self.lock:
            future = self.futures.get(run_id)
        if future is None:
            return None
        if future.cancelled():
            return "CANCELLED"
        if not future.done():
            return "RUNNING"
        return "FAILED" if future.exception() else "COMPLETED"

    def retry(self, run_id: str, task: Callable[[], None]) -> None:
        with self.lock:
            future = self.futures.get(run_id)
            if future and not future.done():
                raise ValueError("job is still running")
            self.futures[run_id] = self.executor.submit(self._run_controlled, run_id, task)

    def cancel(self, run_id: str) -> bool:
        with self.lock:
            future = self.futures.get(run_id)
        run_control.cancel(run_id)
        return bool(future and future.cancel())
