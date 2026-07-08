"""Tests für den Status-Tracker."""
from __future__ import annotations

import asyncio

import pytest

from app.status_tracker import StatusTracker


class TestStatusTracker:
    """Tests für In-Memory Job-Status-Tracking."""

    def test_create_job(self):
        t = StatusTracker()
        job = t.create_job("https://youtu.be/test")
        assert job.url == "https://youtu.be/test"
        assert job.state == "queued"
        assert job.job_id in t._jobs

    @pytest.mark.asyncio
    async def test_update_job(self):
        t = StatusTracker()
        job = t.create_job("https://youtu.be/test")
        await t.update(job.job_id, state="running", step="metadata", progress=0.5)
        assert job.state == "running"
        assert job.step == "metadata"
        assert job.progress == 0.5

    @pytest.mark.asyncio
    async def test_finish_job(self):
        t = StatusTracker()
        job = t.create_job("https://youtu.be/test")
        await t.update(job.job_id, state="running")
        await t.finish(job.job_id, result={"ok": True})
        assert job.state == "done"
        assert job.finished_at is not None
        assert job in t._history

    @pytest.mark.asyncio
    async def test_finish_with_error(self):
        t = StatusTracker()
        job = t.create_job("https://youtu.be/test")
        await t.finish(job.job_id, error="fail")
        assert job.state == "error"
        assert job.error == "fail"

    @pytest.mark.asyncio
    async def test_subscribe_publish(self):
        t = StatusTracker()
        q = await t.subscribe()
        job = t.create_job("https://youtu.be/test")
        # warte kurz, damit publish-task durchläuft
        await asyncio.sleep(0.05)
        # Es sollte mindestens ein Event da sein
        assert not q.empty()
        evt = q.get_nowait()
        assert "event" in evt
        assert "data" in evt

    def test_snapshot(self):
        t = StatusTracker()
        t.create_job("https://youtu.be/1")
        snap = t.snapshot()
        assert "active" in snap
        assert "totals" in snap
        assert snap["totals"]["active"] == 1
