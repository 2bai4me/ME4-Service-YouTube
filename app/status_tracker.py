"""In-Memory Status-Tracker für den Framie-Status-Stream (SSE).

Hält den aktuellen Verarbeitungs-Status pro Job und publiziert Updates
über einen asynchronen Pub/Sub-Bus an die Framie-UI.
"""
from __future__ import annotations

import asyncio
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, List, Optional


@dataclass
class JobStatus:
    """Status eines einzelnen Verarbeitungs-Jobs."""
    job_id: str
    url: str
    worker_id: Optional[str] = None
    started_at: float = field(default_factory=time.time)
    finished_at: Optional[float] = None
    state: str = "queued"  # queued | running | done | error
    step: str = ""
    progress: float = 0.0
    message: str = ""
    result: Optional[dict[str, Any]] = None
    error: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "url": self.url,
            "worker_id": self.worker_id,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "state": self.state,
            "step": self.step,
            "progress": self.progress,
            "message": self.message,
            "duration_sec": (self.finished_at or time.time()) - self.started_at,
            "error": self.error,
        }


class StatusTracker:
    """Hält alle Jobs und broadcastet Updates."""

    def __init__(self, max_history: int = 200) -> None:
        self._jobs: Dict[str, JobStatus] = {}
        self._history: Deque[JobStatus] = deque(maxlen=max_history)
        self._subscribers: List[asyncio.Queue] = []
        self._lock = asyncio.Lock()

    def create_job(self, url: str, worker_id: Optional[str] = None) -> JobStatus:
        job_id = uuid.uuid4().hex[:12]
        job = JobStatus(job_id=job_id, url=url, worker_id=worker_id)
        self._jobs[job_id] = job
        # try fire-and-forget publish; falls kein Loop läuft, ignorieren
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._publish(job.to_dict(), event="job.created"))
        except RuntimeError:
            pass
        return job

    def _publish_sync(self, payload: dict[str, Any], event: str = "message") -> None:
        """Synchroner Publish (für Hooks außerhalb des Event-Loops)."""
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._publish(payload, event=event))
        except RuntimeError:
            pass

    async def update(
        self,
        job_id: str,
        *,
        state: Optional[str] = None,
        step: Optional[str] = None,
        progress: Optional[float] = None,
        message: Optional[str] = None,
        worker_id: Optional[str] = None,
    ) -> None:
        job = self._jobs.get(job_id)
        if not job:
            return
        if state is not None:
            job.state = state
        if step is not None:
            job.step = step
        if progress is not None:
            job.progress = progress
        if message is not None:
            job.message = message
        if worker_id is not None:
            job.worker_id = worker_id
        await self._publish(job.to_dict(), event="job.updated")

    async def finish(
        self,
        job_id: str,
        *,
        result: Optional[dict[str, Any]] = None,
        error: Optional[str] = None,
    ) -> None:
        job = self._jobs.get(job_id)
        if not job:
            return
        job.finished_at = time.time()
        if result is not None:
            job.result = result
            job.state = "done"
            job.progress = 1.0
        if error is not None:
            job.error = error
            job.state = "error"
        self._history.append(job)
        await self._publish(job.to_dict(), event="job.finished")

    def snapshot(self) -> dict[str, Any]:
        return {
            "active": [j.to_dict() for j in self._jobs.values() if j.state in ("queued", "running")],
            "recent": [j.to_dict() for j in list(self._history)[-20:]],
            "totals": {
                "active": sum(1 for j in self._jobs.values() if j.state in ("queued", "running")),
                "done": sum(1 for j in self._history if j.state == "done"),
                "error": sum(1 for j in self._history if j.state == "error"),
            },
        }

    def list_active(self) -> List[JobStatus]:
        return [j for j in self._jobs.values() if j.state in ("queued", "running")]

    # --- SSE Bus ---
    async def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=200)
        self._subscribers.append(q)
        return q

    async def unsubscribe(self, q: asyncio.Queue) -> None:
        if q in self._subscribers:
            self._subscribers.remove(q)

    async def _publish(self, payload: dict[str, Any], event: str = "message") -> None:
        envelope = {"event": event, "data": payload, "ts": time.time()}
        dead: list[asyncio.Queue] = []
        for q in self._subscribers:
            try:
                q.put_nowait(envelope)
            except asyncio.QueueFull:
                dead.append(q)
        for q in dead:
            await self.unsubscribe(q)


# Singleton
status_tracker = StatusTracker()
