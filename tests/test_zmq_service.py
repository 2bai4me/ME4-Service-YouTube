"""Tests für die ZMQ-Service-Tool-Liste (MCP-konform)."""
from __future__ import annotations

from app.config import settings
from app.loadbalancer import WorkerPool
from app.zmq_service import ZMQService


class TestZMQService:
    """Tests für MCP-konforme Tool-Liste."""

    def test_tools_list_includes_required(self):
        pool = WorkerPool(host="127.0.0.1", base_port=0, size=0)
        zmq = ZMQService(pool=pool, port=0)
        resp = zmq._tools_list("rid-1")
        assert "result" in resp
        tools = resp["result"]["tools"]
        names = {t["name"] for t in tools}
        # Pflicht-Tools
        assert "ping" in names
        assert "get_manifest" in names
        assert "health" in names
        assert "shutdown" in names
        # Feature-Tools
        assert "get_metadata" in names
        assert "get_transcript" in names
        assert "get_comments" in names
        assert "download" in names
        assert "process" in names

    def test_init_handshake(self):
        pool = WorkerPool(host="127.0.0.1", base_port=0, size=0)
        zmq = ZMQService(pool=pool, port=0)
        resp = zmq._init("rid-1", {})
        assert resp["result"]["protocolVersion"] == "2024-11-05"
        assert resp["result"]["serverInfo"]["name"] == "ME4-YOUTUBE"

    def test_manifest_contains_loadbalancer(self):
        # Test: Manifest reflektiert die konfigurierte Pool-Größe
        pool = WorkerPool(host="127.0.0.1", base_port=0)
        zmq = ZMQService(pool=pool, port=0)
        m = zmq._manifest()
        assert m["id"] == settings.service_id
        assert m["version"] == settings.service_version
        # Manifest zeigt settings.worker_count (Test: WORKER_COUNT=1)
        assert m["loadbalancer"]["pool_size"] == settings.worker_count
        assert m["loadbalancer"]["strategy"] == settings.loadbalancer_strategy
        assert "ports" in m
        assert "framie_endpoint" in m
        assert m["loadbalancer"]["zmq_port"] == settings.loadbalancer_zmq_port

    def test_ping_doesnt_need_auth(self, monkeypatch):
        from app.config import settings
        monkeypatch.setattr(settings, "api_key", "secret")
        import asyncio
        pool = WorkerPool(host="127.0.0.1", base_port=0, size=0)
        zmq = ZMQService(pool=pool, port=0)
        resp = asyncio.run(zmq._tools_call("rid", {"name": "ping", "arguments": {}}))
        assert "result" in resp
        assert "error" not in resp

    def test_process_needs_auth(self, monkeypatch):
        from app.config import settings
        monkeypatch.setattr(settings, "api_key", "secret")
        import asyncio
        pool = WorkerPool(host="127.0.0.1", base_port=0, size=0)
        zmq = ZMQService(pool=pool, port=0)
        resp = asyncio.run(zmq._tools_call("rid", {"name": "process", "arguments": {"url": "x"}}))
        assert "error" in resp
        assert resp["error"]["code"] == -32001
