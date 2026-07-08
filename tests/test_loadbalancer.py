"""Tests für den Worker-Pool + Loadbalancer (ohne Netzwerk)."""
from __future__ import annotations

import asyncio

import pytest

from app.exceptions import WorkerUnavailableError
from app.loadbalancer import WorkerPool
from app.worker import Worker


class TestWorkerPool:
    """Tests für die Worker-Pool-Logik (Mock-Worker)."""

    def test_select_worker_no_workers_raises(self):
        pool = WorkerPool(host="127.0.0.1", base_port=0, size=0)
        with pytest.raises(WorkerUnavailableError):
            pool.select_worker()

    def test_select_worker_round_robin(self):
        pool = WorkerPool(host="127.0.0.1", base_port=0, size=3)
        # Fake-Worker direkt injizieren
        for i in range(3):
            w = Worker(worker_id=f"w-{i}", host="127.0.0.1", port=9000 + i)
            w.last_heartbeat = 9999999999  # nicht abgelaufen
            pool.workers.append(w)
        # Round Robin
        s = "round_robin"
        a = pool.select_worker(s)
        b = pool.select_worker(s)
        c = pool.select_worker(s)
        assert a.worker_id != b.worker_id != c.worker_id

    def test_select_worker_least_loaded(self):
        pool = WorkerPool(host="127.0.0.1", base_port=0, size=3)
        w0 = Worker(worker_id="w-0", host="127.0.0.1", port=9000)
        w1 = Worker(worker_id="w-1", host="127.0.0.1", port=9001)
        w2 = Worker(worker_id="w-2", host="127.0.0.1", port=9002)
        w0.current_load = 5
        w1.current_load = 0
        w2.current_load = 10
        for w in (w0, w1, w2):
            w.last_heartbeat = 9999999999
            pool.workers.append(w)
        # Least loaded = w-1
        assert pool.select_worker("least_loaded").worker_id == "w-1"

    def test_status(self):
        pool = WorkerPool(host="127.0.0.1", base_port=0, size=2)
        w = Worker(worker_id="w-1", host="127.0.0.1", port=9000)
        w.last_heartbeat = 9999999999
        w.total_processed = 42
        pool.workers.append(w)
        s = pool.status()
        assert s["size"] == 2  # configured size
        assert s["alive"] == 1  # nur 1 injiziert
        assert s["total_processed"] == 42
        assert "workers" in s
