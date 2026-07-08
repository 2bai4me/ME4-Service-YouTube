"""Tests für die HTTP-API (Smoke-Tests ohne echte YouTube-Calls)."""
from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.http_api import build_app
from app.loadbalancer import WorkerPool
from app.zmq_service import ZMQService


class TestHTTPApi:
    """Smoke-Tests der HTTP-Endpunkte."""

    def test_root(self):
        pool = WorkerPool(host="127.0.0.1", base_port=0, size=0)
        zmq = ZMQService(pool=pool, port=0)
        app = build_app(pool, zmq)
        with TestClient(app) as client:
            r = client.get("/")
            assert r.status_code == 200
            data = r.json()
            assert data["service"] == "ME4-YOUTUBE"

    def test_health(self):
        pool = WorkerPool(host="127.0.0.1", base_port=0, size=0)
        zmq = ZMQService(pool=pool, port=0)
        app = build_app(pool, zmq)
        with TestClient(app) as client:
            r = client.get("/api/health")
            assert r.status_code == 200
            data = r.json()
            assert data["status"] == "ok"
            assert "loadbalancer" in data

    def test_manifest(self):
        pool = WorkerPool(host="127.0.0.1", base_port=0, size=0)
        zmq = ZMQService(pool=pool, port=0)
        app = build_app(pool, zmq)
        with TestClient(app) as client:
            r = client.get("/api/manifest")
            assert r.status_code == 200
            data = r.json()
            assert data["service_id"] == "ME4-YOUTUBE"
            assert "loadbalancer" in data

    def test_status(self):
        pool = WorkerPool(host="127.0.0.1", base_port=0, size=0)
        zmq = ZMQService(pool=pool, port=0)
        app = build_app(pool, zmq)
        with TestClient(app) as client:
            r = client.get("/api/status")
            assert r.status_code == 200
            data = r.json()
            assert "totals" in data
            assert "active" in data

    def test_process_unauthorized(self, monkeypatch):
        from app.config import settings
        monkeypatch.setattr(settings, "api_key", "secret")
        pool = WorkerPool(host="127.0.0.1", base_port=0, size=0)
        zmq = ZMQService(pool=pool, port=0)
        app = build_app(pool, zmq)
        with TestClient(app) as client:
            r = client.post("/api/process", json={"url": "https://youtu.be/dQw4w9WgXcQ"})
            assert r.status_code == 401
