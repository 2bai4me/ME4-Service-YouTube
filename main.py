"""ME4-YouTube — Haupteinstiegspunkt.

Diese Datei ist der VERBINDLICHE Service-Start der ME4-YouTube-Schnittstelle.

Boot-Sequenz (in fester Reihenfolge, dokumentiert in SERVICE_START.md):
  1. Logging
  2. Worker-Pool aufbauen
  3. ZMQ-Lastbalancer hochfahren
  4. ZMQ-Hauptservice starten
  5. WSSP-15 Heartbeat emittieren
  6. HTTP-API + Framie-UI starten
  7. SM-Producer-Anbindung initialisieren
  8. Status: READY → Framie zeigt Live-Stream

Modi:
  python main.py                  # Standard: alle Layer starten
  python main.py --mcp-stdio      # MCP stdio (für Agenten)
  python main.py --no-workers     # ohne Worker-Pool
  python main.py --port 8888      # HTTP-Port überschreiben
"""
from __future__ import annotations

import argparse
import asyncio
import os
import signal
import sys
import time
import webbrowser
from pathlib import Path
from typing import Optional

import uvicorn

from app import __service_id__, __version__
from app.config import settings
from app.http_api import build_app
from app.loadbalancer import LoadBalancerZMQ, WorkerPool
from app.logging_config import get_logger, setup_logging
from app.zmq_service import ZMQService

# Banner
BANNER = f"""
+================================================================+
|                  {__service_id__} v{__version__}                      |
|         YouTube Content Extraction Service                    |
|         MCP + ZMQ + HTTP + WSSP-15 + Framie                   |
+================================================================+
"""

logger = get_logger("main")


class ServiceBootstrap:
    """Boot-Manager — startet alle Layer in fester Reihenfolge."""

    def __init__(self, no_workers: bool = False, no_browser: bool = False):
        self.no_workers = no_workers
        self.no_browser = no_browser
        self.pool: Optional[WorkerPool] = None
        self.zmq_main: Optional[ZMQService] = None
        self.zmq_lb: Optional[LoadBalancerZMQ] = None
        self.emitter = None
        self.http_server: Optional[uvicorn.Server] = None

    async def boot(self) -> None:
        """Führt die Boot-Sequenz aus."""
        print(BANNER)
        logger.info("Service-Start: %s v%s", __service_id__, __version__)
        logger.info("Modus: %s", "no-workers" if self.no_workers else "full")

        # === 1. Worker-Pool ===
        if not self.no_workers:
            logger.info("-> [1/5] Starte Worker-Pool (%d Worker)...", settings.worker_count)
            self.pool = WorkerPool(
                host="127.0.0.1",
                base_port=settings.worker_base_port,
                size=settings.worker_count,
                has_api_key=settings.api_key,
            )
            await self.pool.start()
        else:
            logger.info("-> [1/5] Worker-Pool uebersprungen (--no-workers)")
            self.pool = WorkerPool(host="127.0.0.1", base_port=settings.worker_base_port, size=0)

        # === 2. ZMQ-Lastbalancer (MCP-Loadbalancer) ===
        logger.info("-> [2/5] Starte ZMQ-Loadbalancer auf Port %d...", settings.loadbalancer_zmq_port)
        self.zmq_lb = LoadBalancerZMQ(pool=self.pool, port=settings.loadbalancer_zmq_port)
        await self.zmq_lb.start()

        # === 3. ZMQ-Hauptservice ===
        logger.info("-> [3/5] Starte ZMQ-Hauptservice auf Port %d...", settings.zmq_port)
        self.zmq_main = ZMQService(pool=self.pool, port=settings.zmq_port)
        await self.zmq_main.start()

        # === 4. WSSP-15 Heartbeat ===
        try:
            from wssp15.heartbeat_emitter import HeartbeatEmitter, StatusCode
            logger.info("-> [4/5] Starte WSSP-15 Heartbeat auf Port %d...", settings.wssp15_port)
            self.emitter = HeartbeatEmitter(
                service_id=settings.service_id,
                version=settings.service_version,
                ws_port=settings.wssp15_port,
            )
            self.emitter.full_manifest = self.zmq_main._manifest()
            self.emitter.update_ui_manifest({
                "actions": self.zmq_main._manifest().get("actions", []),
                "api_docs": f"http://localhost:{settings.http_port}/docs",
            })
            self.emitter.start()
        except Exception as e:  # noqa: BLE001
            logger.warning("WSSP-15 Heartbeat fehlgeschlagen: %s", e)

        # === 5. HTTP-API + Framie-UI ===
        logger.info("-> [5/5] Starte HTTP-API + Framie-UI auf Port %d...", settings.http_port)
        app = build_app(pool=self.pool, zmq_service=self.zmq_main)
        config = uvicorn.Config(
            app, host=settings.host, port=settings.http_port,
            log_level="warning", access_log=False,
        )
        self.http_server = uvicorn.Server(config)
        asyncio.create_task(self.http_server.serve())
        # Warten bis ready
        for _ in range(50):
            if self.http_server.started:
                break
            await asyncio.sleep(0.1)

        # === READY ===
        self._print_ready_banner()

        # SM-Producer-Anbindung testen
        if settings.sm_producer_enabled:
            asyncio.create_task(self._test_sm_producer())

        # Framie im Browser öffnen (optional)
        if not self.no_browser and os.environ.get("ME4_NO_BROWSER") != "1":
            framie_url = f"http://localhost:{settings.http_port}/ui/index.html"
            logger.info("Öffne Framie-UI: %s", framie_url)
            try:
                webbrowser.open(framie_url)
            except Exception:  # noqa: BLE001
                pass

        # Signal Handler
        self._install_signal_handlers()

        # Warten bis Shutdown
        try:
            while True:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass

    def _print_ready_banner(self) -> None:
        """Druckt das READY-Banner mit allen Endpunkten."""
        print()
        print("+----------------------------------------------------------------+")
        print("|  [OK]  SERVICE BEREIT - ME4-YouTube v1.0.0                     |")
        print("+----------------------------------------------------------------+")
        print(f"|  HTTP API:        http://localhost:{settings.http_port}/docs")
        print(f"|  Framie-UI:       http://localhost:{settings.http_port}/ui/index.html")
        print(f"|  Health:          http://localhost:{settings.http_port}/api/health")
        print(f"|  ZMQ Main:        tcp://localhost:{settings.zmq_port}")
        print(f"|  ZMQ Loadbalancer: tcp://localhost:{settings.loadbalancer_zmq_port}")
        print(f"|  WSSP-15:         ws://localhost:{settings.wssp15_port}")
        print(f"|  Worker-Pool:     {settings.worker_count} Instanzen ab :{settings.worker_base_port}")
        print("+----------------------------------------------------------------+")
        print("|  Framie-Status direkt im Browser sichtbar.                     |")
        print("|  Ctrl+C fuer sauberen Shutdown.                                |")
        print("+----------------------------------------------------------------+")
        print()
        logger.info("READY - alle Layer laufen")

    async def _test_sm_producer(self) -> None:
        """Prüft SM-Producer-Anbindung (non-blocking)."""
        try:
            from app.sm_producer_client import SMProducerClient
            client = SMProducerClient()
            await asyncio.wait_for(client.health(), timeout=3)
            logger.info("SM-Producer erreichbar: %s", settings.sm_producer_url)
        except Exception as e:  # noqa: BLE001
            logger.info("SM-Producer nicht erreichbar (kann später starten): %s", e)

    def _install_signal_handlers(self) -> None:
        """Installiert Signal-Handler für graceful shutdown."""
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, lambda: asyncio.create_task(self.shutdown()))
            except (NotImplementedError, RuntimeError):
                pass

    async def shutdown(self) -> None:
        """Fährt alle Layer sauber herunter."""
        logger.info("Shutdown wird eingeleitet…")
        if self.http_server:
            self.http_server.should_exit = True
        if self.emitter:
            try:
                self.emitter.stop()
            except Exception:  # noqa: BLE001
                pass
        if self.zmq_main:
            await self.zmq_main.stop()
        if self.zmq_lb:
            await self.zmq_lb.stop()
        if self.pool:
            await self.pool.stop()
        logger.info("Shutdown abgeschlossen")
        # Event-Loop beenden
        asyncio.get_event_loop().stop()


async def run_mcp_stdio() -> None:
    """Startet nur den MCP-stdio-Modus (für Agenten)."""
    from app.mcp_stdio import MCPStdio

    setup_logging()
    logger.info("MCP stdio mode")
    pool = WorkerPool(host="127.0.0.1", base_port=settings.worker_base_port, size=1, has_api_key=settings.api_key)
    await pool.start()
    try:
        server = MCPStdio(pool=pool)
        await server.run()
    finally:
        await pool.stop()


def main() -> None:
    """Entry-Point."""
    # Windows: UTF-8 für stdout erzwingen
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass

    parser = argparse.ArgumentParser(description="ME4-YouTube Service")
    parser.add_argument("--mcp-stdio", action="store_true", help="MCP stdio mode (fuer Agenten)")
    parser.add_argument("--no-workers", action="store_true", help="Ohne Worker-Pool starten")
    parser.add_argument("--no-browser", action="store_true", help="Framie-UI nicht automatisch im Browser oeffnen")
    parser.add_argument("--port", type=int, help="HTTP-Port ueberschreiben")
    parser.add_argument("--host", type=str, help="HTTP-Host ueberschreiben")
    args = parser.parse_args()

    setup_logging()

    if args.port:
        settings.http_port = args.port
    if args.host:
        settings.host = args.host

    if args.mcp_stdio:
        asyncio.run(run_mcp_stdio())
    else:
        bootstrap = ServiceBootstrap(no_workers=args.no_workers, no_browser=args.no_browser)
        try:
            asyncio.run(bootstrap.boot())
        except KeyboardInterrupt:
            print("\n[beendet durch Benutzer]")


if __name__ == "__main__":
    main()
