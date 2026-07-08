"""Worker-Pool + Loadbalancer (MCP-konformer ZMQ-Server).

Verwaltet N Worker-Instanzen, verteilt eingehende Jobs nach
Strategie (round_robin | least_loaded | random) und überwacht
Health via Heartbeat.
"""
from __future__ import annotations

import asyncio
import json
import random
import time
import uuid
from typing import Any, Optional

import zmq
import zmq.asyncio

from app.auth import verify_zmq_key
from app.config import settings
from app.exceptions import WorkerUnavailableError
from app.logging_config import get_logger
from app.worker import Worker

logger = get_logger(__name__)


class WorkerPool:
    """Verwaltet Worker + Loadbalancing."""

    def __init__(self, host: str = "127.0.0.1", base_port: Optional[int] = None,
                 size: Optional[int] = None, has_api_key: str = ""):
        self.host = host
        self.base_port = base_port or settings.worker_base_port
        self.size = size or settings.worker_count
        self.has_api_key = has_api_key or settings.api_key
        self.workers: list[Worker] = []
        self._rr_index = 0
        self._lock = asyncio.Lock()
        self._health_task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        """Startet alle Worker."""
        async with self._lock:
            logger.info("starting %d workers (base_port=%d)...", self.size, self.base_port)
            for i in range(self.size):
                wid = f"worker-{i+1:02d}"
                port = self.base_port + i
                w = Worker(worker_id=wid, host=self.host, port=port, has_api_key=self.has_api_key)
                await w.start()
                self.workers.append(w)
                logger.info("  [OK] %s on %s:%d", wid, w.host, w.port)
            # Health-Watchdog
            self._health_task = asyncio.create_task(self._health_loop())
            logger.info("worker pool ready (%d workers)", len(self.workers))

    async def stop(self) -> None:
        """Stoppt alle Worker."""
        if self._health_task:
            self._health_task.cancel()
        for w in self.workers:
            await w.stop()
        self.workers.clear()
        logger.info("worker pool stopped")

    async def _health_loop(self) -> None:
        """Überwacht Worker-Health alle 10s."""
        try:
            while True:
                await asyncio.sleep(10)
                alive = sum(1 for w in self.workers if w.is_alive())
                if alive < len(self.workers):
                    dead = [w.worker_id for w in self.workers if not w.is_alive()]
                    logger.warning("workers down: %s", dead)
        except asyncio.CancelledError:
            pass

    def select_worker(self, strategy: Optional[str] = None) -> Worker:
        """Wählt einen Worker nach Strategie."""
        alive = [w for w in self.workers if w.is_alive()]
        if not alive:
            raise WorkerUnavailableError("no workers alive")
        strat = strategy or settings.loadbalancer_strategy
        if strat == "round_robin":
            self._rr_index = (self._rr_index + 1) % len(alive)
            return alive[self._rr_index]
        if strat == "least_loaded":
            return min(alive, key=lambda w: w.current_load)
        # random fallback
        return random.choice(alive)

    def status(self) -> dict[str, Any]:
        """Pool-Status für Loadbalancer-Reports."""
        return {
            "size": self.size,
            "alive": sum(1 for w in self.workers if w.is_alive()),
            "total_load": sum(w.current_load for w in self.workers),
            "total_processed": sum(w.total_processed for w in self.workers),
            "workers": [w.heartbeat() for w in self.workers],
            "strategy": settings.loadbalancer_strategy,
        }


class LoadBalancerZMQ:
    """ZMQ REQ/REP Server als MCP-Loadbalancer."""

    def __init__(self, pool: WorkerPool, port: Optional[int] = None):
        self.pool = pool
        self.port = port or settings.loadbalancer_zmq_port
        self._ctx: Optional[zmq.asyncio.Context] = None
        self._socket: Optional[zmq.asyncio.Socket] = None
        self._task: Optional[asyncio.Task] = None
        self._running = False

    async def start(self) -> None:
        """Startet den Loadbalancer-ZMQ-Listener."""
        self._ctx = zmq.asyncio.Context()
        self._socket = self._ctx.socket(zmq.REP)
        self._socket.setsockopt(zmq.LINGER, 0)
        self._socket.bind(f"tcp://*:{self.port}")
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info("LoadBalancer-ZMQ listening on tcp://*:%d", self.port)

    async def stop(self) -> None:
        """Stoppt den Loadbalancer."""
        self._running = False
        if self._task:
            self._task.cancel()
        if self._socket:
            self._socket.close()
        if self._ctx:
            self._ctx.term()
        logger.info("LoadBalancer-ZMQ stopped")

    async def _loop(self) -> None:
        """Haupt-Loop: nimmt Requests entgegen, leitet an Worker weiter."""
        try:
            while self._running:
                msg = await self._socket.recv_json()  # type: ignore[union-attr]
                resp = await self._handle(msg)
                await self._socket.send_json(resp)  # type: ignore[union-attr]
        except asyncio.CancelledError:
            pass

    async def _handle(self, msg: dict[str, Any]) -> dict[str, Any]:
        """Verarbeitet eine eingehende MCP-Nachricht."""
        method = msg.get("method", "")
        if method == "tools/list":
            return self._tools_list()
        if method == "tools/call":
            return await self._tools_call(msg.get("params", {}))
        return {"jsonrpc": "2.0", "id": msg.get("id"), "error": {"code": -32601, "message": f"unknown method: {method}"}}

    def _tools_list(self) -> dict[str, Any]:
        """Liefert die Liste der verfügbaren Loadbalancer-Tools."""
        tools = [
            {"name": "ping", "description": "Loadbalancer-Health", "public": True},
            {"name": "get_manifest", "description": "UI-Manifest", "public": True},
            {"name": "health", "description": "Detaillierter Pool-Status", "public": True},
            {"name": "status", "description": "Worker-Status", "public": True},
            {"name": "process", "description": "YouTube-Job an Worker weiterleiten", "public": False},
            {"name": "shutdown", "description": "Pool herunterfahren", "public": False},
        ]
        return {"jsonrpc": "2.0", "id": "list", "result": {"tools": tools}}

    async def _tools_call(self, params: dict[str, Any]) -> dict[str, Any]:
        """Bearbeitet einen Tool-Aufruf."""
        name = params.get("name", "")
        args = params.get("arguments", {}) or {}
        # Auth (außer public)
        if name not in {"ping", "get_manifest", "health", "status", "tools/list"}:
            try:
                verify_zmq_key(args)
            except Exception as e:  # noqa: BLE001
                return {"jsonrpc": "2.0", "id": "auth", "error": {"code": -32001, "message": str(e)}}

        if name == "ping":
            return {"jsonrpc": "2.0", "id": "ping", "result": {"status": "ok", "service": "ME4-YOUTUBE-LB"}}
        if name == "get_manifest":
            return {
                "jsonrpc": "2.0", "id": "manifest",
                "result": {
                    "service_id": "ME4-YOUTUBE-LB",
                    "service_name": "ME4-YouTube Loadbalancer",
                    "type": "loadbalancer",
                    "version": "1.0.0",
                    "zmq_port": self.port,
                    "pool_size": self.pool.size,
                },
            }
        if name in ("health", "status"):
            return {"jsonrpc": "2.0", "id": name, "result": self.pool.status()}
        if name == "process":
            return await self._forward_to_worker(args)
        if name == "shutdown":
            asyncio.create_task(self.pool.stop())
            return {"jsonrpc": "2.0", "id": "shutdown", "result": {"status": "shutting_down"}}
        return {"jsonrpc": "2.0", "id": name, "error": {"code": -32602, "message": f"unknown tool: {name}"}}

    async def _forward_to_worker(self, args: dict[str, Any]) -> dict[str, Any]:
        """Leitet einen Job an einen Worker weiter."""
        try:
            worker = self.pool.select_worker()
        except WorkerUnavailableError as e:
            return {"jsonrpc": "2.0", "id": "process", "error": {"code": -32002, "message": str(e)}}

        import httpx
        url = f"http://{worker.host}:{worker.port}/process"
        try:
            async with httpx.AsyncClient(timeout=settings.request_timeout_sec) as c:
                r = await c.post(url, json=args)
                r.raise_for_status()
                data = r.json()
        except Exception as e:  # noqa: BLE001
            return {"jsonrpc": "2.0", "id": "process", "error": {"code": -32003, "message": f"worker {worker.worker_id} failed: {e}"}}
        return {
            "jsonrpc": "2.0", "id": "process",
            "result": {"content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False)}]},
        }
