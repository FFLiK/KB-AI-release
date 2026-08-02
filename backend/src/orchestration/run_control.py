"""Cooperative cancellation and analysis-job deadline registry."""
from __future__ import annotations

import time
from threading import Lock


class RunControlRegistry:
    def __init__(self) -> None:
        self._lock = Lock()
        self._deadlines: dict[str, float] = {}
        self._cancelled: set[str] = set()

    def begin(self, run_id: str, timeout_seconds: float) -> None:
        with self._lock:
            self._cancelled.discard(run_id)
            self._deadlines[run_id] = time.monotonic() + timeout_seconds

    def finish(self, run_id: str) -> None:
        with self._lock:
            self._deadlines.pop(run_id, None)
            self._cancelled.discard(run_id)

    def cancel(self, run_id: str) -> None:
        with self._lock:
            self._cancelled.add(run_id)

    def stop_reason(self, run_id: str) -> str | None:
        with self._lock:
            if run_id in self._cancelled:
                return "USER_CANCELLED"
            deadline = self._deadlines.get(run_id)
        if deadline is not None and time.monotonic() >= deadline:
            return "ANALYSIS_JOB_TIMEOUT"
        return None


run_control = RunControlRegistry()
