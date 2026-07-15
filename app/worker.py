"""Sub-Worker: einzelne Verarbeitungs-Instanz mit eigener HTTP-API.

Jeder Worker hat:
- eigenen HTTP-Port
- eigenen Health-Status
- einen Orchestrator
- einen Heartbeat
"""
from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any, Optional

import uvicorn
from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import JSONResponse

from app.auth import verify_http_key
from app.config import settings
from app.orchestrator import Orchestrator
from app.status_tracker import status_tracker


class Worker:
    """Ein einzelner Worker-Prozess im Pool."""

    def __init__(self, worker_id: str, host: str, port: int, has_api_key: str = ""):
        self.worker_id = worker_id
        self.host = host
        self.port = port
        self.has_api_key = has_api_key
        self.started_at = time.time()
        self.last_heartbeat = time.time()
        self.current_load = 0
        self.total_processed = 0
        self._server: Optional[uvicorn.Server] = None
        self._orchestrator = Orchestrator(worker_id=worker_id)
        self._app = self._build_app()

    def _build_app(self) -> FastAPI:
        app = FastAPI(
            title=f"ME4-YouTube Worker {self.worker_id}",
            version=settings.service_version,
        )

        @app.get("/")
        async def root():
            return {
                "worker_id": self.worker_id,
                "status": "up",
                "uptime_sec": time.time() - self.started_at,
            }

        @app.get("/health")
        async def health():
            return {
                "status": "up",
                "worker_id": self.worker_id,
                "current_load": self.current_load,
                "total_processed": self.total_processed,
                "uptime_sec": time.time() - self.started_at,
            }

        @app.post("/process")
        async def process(req: dict[str, Any]):
            """Verarbeitet eine YouTube-URL."""
            from app.models import ProcessRequest

            self.current_load += 1
            try:
                pyd = ProcessRequest(**req)
                resp = await self._orchestrator.process(pyd)
                self.total_processed += 1
                return JSONResponse(content=resp.model_dump())
            except Exception as e:  # noqa: BLE001
                raise HTTPException(status_code=400, detail=str(e))
            finally:
                self.current_load = max(0, self.current_load - 1)

        return app

    async def start(self) -> None:
        """Startet den Worker-Server im Hintergrund."""
        config = uvicorn.Config(
            self._app,
            host=self.host,
            port=self.port,
            log_level="warning",
            access_log=False,
        )
        self._server = uvicorn.Server(config)
        asyncio.create_task(self._server.serve())
        # Warten bis ready
        for _ in range(50):
            if self._server.started:
                break
            await asyncio.sleep(0.1)
        self.last_heartbeat = time.time()
        # Heartbeat-Task: aktualisiert last_heartbeat alle 5s
        asyncio.create_task(self._heartbeat_loop())

    async def _heartbeat_loop(self) -> None:
        """Sendet periodisch Heartbeats, damit der Loadbalancer Worker als 'alive' sieht."""
        try:
            while True:
                await asyncio.sleep(5)
                if self._server and self._server.started:
                    self.last_heartbeat = time.time()
        except asyncio.CancelledError:
            pass

    async def stop(self) -> None:
        """Stoppt den Worker."""
        if self._server:
            self._server.should_exit = True

    def heartbeat(self) -> dict[str, Any]:
        """Aktualisiert Heartbeat und liefert Status."""
        self.last_heartbeat = time.time()
        return {
            "worker_id": self.worker_id,
            "host": self.host,
            "port": self.port,
            "status": "up" if self.is_alive() else "down",
            "current_load": self.current_load,
            "total_processed": self.total_processed,
            "uptime_sec": time.time() - self.started_at,
            "last_heartbeat": self.last_heartbeat,
        }

    def is_alive(self) -> bool:
        """True, wenn letzte Heartbeat < 30s her."""
        return (time.time() - self.last_heartbeat) < 30.0
