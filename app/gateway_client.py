"""ME4-YouTube — nativer Heartbeat-Adapter für me4-service-gateway.

Phase 2.1 (Pilot): YouTube registriert sich SELBST beim Gateway (ohne Sidecar).
Der Sidecar aus Phase 2.0 bleibt parallel als Fallback aktiv (kein Disabling).

Funktionsumfang:
- Periodische Heartbeats (5s-Intervall, konfigurierbar) gegen POST /registry/heartbeat
- Health-Check gegen das eigene /api/health-Endpoint vor jedem Heartbeat
- Echtzeit-Metriken: CPU%, RAM%, active_requests, avg_latency_ms, error_rate
- Persistente instance_id (UUID4 in DATA_DIR/instance_id) → Doppelregistrierung-sicher
- Optionaler Shutdown-Hook (Deregister beim sauberen Beenden)
- Manifest-Generierung (name/version/capabilities/endpoints) gem. Standard 4/7

ENV-Variablen (alle optional, Defaults aus settings):
    GATEWAY_URL              default: http://localhost:9000
    GATEWAY_API_KEY          default: <settings.api_key oder leer>
    GATEWAY_REGISTRATION     default: true (false → Adapter disabled)
    HEARTBEAT_INTERVAL_SEC   default: 5
    SERVICE_BUS_NAME         default: me4-youtube
    SERVICE_CAPABILITIES     default: youtube-metadata,transcript,download,comments
"""
from __future__ import annotations

import asyncio
import logging
import os
import platform
import socket
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx
import psutil

from app.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Defaults (gemaess ME4-Service-Bus-Standard v1.0)
# ---------------------------------------------------------------------------
DEFAULT_GATEWAY_URL = "http://localhost:9000"
DEFAULT_INTERVAL = 5  # Sekunden
DEFAULT_NAME = "me4-youtube"
DEFAULT_CAPABILITIES = "youtube-metadata,transcript,download,comments"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _env(name: str, default: str) -> str:
    """Liest ENV-Var mit Default -- explizit, kein stillschweigendes Pydantic-Fallback."""
    v = os.environ.get(name)
    return v if v is not None and v != "" else default


def _load_or_create_instance_id(data_dir: Path) -> str:
    """Stabile instance_id pro Prozess-Lauf-Pfad.

    Beim ersten Start: UUID4 generieren + in DATA_DIR/instance_id persistieren.
    Folge-Restarts: gleiche ID lesen -> idempotente Registrierung im Gateway.
    Bei DATA_DIR-Wechsel: neue ID (gewollt -- Pfad ist Identitaetsanker).
    """
    path = data_dir / "instance_id"
    try:
        if path.exists():
            stored = path.read_text(encoding="utf-8").strip()
            if stored and len(stored) >= 8:
                return stored
        # Neu generieren
        host = platform.node().split(".")[0] or "host"
        new_id = f"me4-youtube-{host}-{uuid.uuid4().hex[:8]}"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(new_id, encoding="utf-8")
        return new_id
    except OSError as e:
        # Fallback ohne Persistenz -- funktioniert, aber ueberlebt Restart nicht
        logger.warning("instance_id-Persistenz fehlgeschlagen (%s) -- verwende ephemere ID", e)
        return f"me4-youtube-ephemeral-{uuid.uuid4().hex[:8]}"


def _build_manifest(base_url: str, capabilities: list[str]) -> dict:
    """Manifest gemaess Service-Bus-Standard 4/7 (name/version/capabilities/endpoints)."""
    return {
        "name": _env("SERVICE_BUS_NAME", DEFAULT_NAME),
        "service_id": settings.service_id,
        "version": settings.service_version,
        "type": "service",
        "capabilities": capabilities,
        "endpoints": {
            "health": f"{base_url}/api/health",
            "manifest": f"{base_url}/api/manifest",
            "metadata": f"{base_url}/api/youtube/metadata",
            "transcript": f"{base_url}/api/youtube/transcript",
            "download": f"{base_url}/api/youtube/download",
            "comments": f"{base_url}/api/youtube/comments",
            "process": f"{base_url}/api/process",
        },
        "metadata": {
            "framework": "FastAPI",
            "language": "Python",
            "version": settings.service_version,
            "conforms_to": "ME4-Service-Bus-Standard-v1.0",
        },
        "health_metrics": [
            "cpu_percent",
            "memory_percent",
            "active_requests",
            "avg_latency_ms",
            "error_rate",
        ],
    }


# ---------------------------------------------------------------------------
# Metrik-Sammler
# ---------------------------------------------------------------------------

class MetricsCollector:
    """Sammelt CPU/Mem/Latenz/Req-Metriken aus dem laufenden YouTube-Prozess.

    Hinweis: CPU% ueber psutil ruft Process.cpu_percent(interval=None) auf,
    das einen Delta zum vorherigen Aufruf liefert. Der erste Aufruf
    liefert 0.0 -- das ist erwartet (psutil-API).
    """

    def __init__(self):
        self._proc = psutil.Process(os.getpid())
        self._proc.cpu_percent(interval=None)  # Baseline
        # Aktive-Requests-Zaehler -- wird vom FastAPI-Middleware aktualisiert
        self.active_requests: int = 0
        self.total_requests: int = 0
        self.error_count: int = 0
        # Latenz-Fenster (letzte 100 Requests)
        self._latency_window: list[float] = []
        self._latency_maxlen = 100
        self._started_at = time.monotonic()

    def record_request(self, latency_ms: float, is_error: bool = False):
        """Vom FastAPI-Middleware pro abgeschlossenen Request aufrufen."""
        self.total_requests += 1
        if is_error:
            self.error_count += 1
        self._latency_window.append(latency_ms)
        if len(self._latency_window) > self._latency_maxlen:
            self._latency_window.pop(0)

    def snapshot(self) -> dict:
        """Liefert den Metrik-Snapshot fuer den naechsten Heartbeat."""
        # CPU nicht-blockierend abfragen
        cpu = self._proc.cpu_percent(interval=None)
        # Memory
        mem = self._proc.memory_percent()
        # Latenz-Median (robuster als Mittelwert)
        if self._latency_window:
            sorted_lat = sorted(self._latency_window)
            median = sorted_lat[len(sorted_lat) // 2]
        else:
            median = 0.0
        # Error-Rate
        err_rate = (self.error_count / self.total_requests) if self.total_requests else 0.0

        return {
            "cpu_percent": round(cpu, 2),
            "memory_percent": round(mem, 2),
            "active_requests": self.active_requests,
            "avg_latency_ms": round(median, 2),
            "total_requests": self.total_requests,
            "error_rate": round(err_rate, 4),
        }


# ---------------------------------------------------------------------------
# Heartbeat-Loop
# ---------------------------------------------------------------------------

class GatewayClient:
    """Long-running Heartbeat-Adapter. Start mit `await client.start()`."""

    def __init__(self, metrics: Optional[MetricsCollector] = None):
        self._enabled = _env("GATEWAY_REGISTRATION", "true").lower() in ("1", "true", "yes", "on")
        self._gateway_url = _env("GATEWAY_URL", DEFAULT_GATEWAY_URL).rstrip("/")
        self._api_key = _env("GATEWAY_API_KEY", settings.api_key)
        self._interval = int(_env("HEARTBEAT_INTERVAL_SEC", str(DEFAULT_INTERVAL)))
        self._data_dir = Path(_env("DATA_DIR", settings.data_dir))
        self._instance_id = _load_or_create_instance_id(self._data_dir)
        self._capabilities = [
            c.strip() for c in _env("SERVICE_CAPABILITIES", DEFAULT_CAPABILITIES).split(",") if c.strip()
        ]
        # base_url: bevorzugt ENV, sonst http://<host>:<port>
        self._base_url = _env(
            "SERVICE_BASE_URL",
            f"http://{socket.gethostbyname(socket.gethostname())}:{settings.http_port}",
        )

        self.metrics = metrics or MetricsCollector()
        self._task: Optional[asyncio.Task] = None
        self._client: Optional[httpx.AsyncClient] = None
        self._stopped = asyncio.Event()
        self._health_url = f"{self._base_url}/api/health"

    @property
    def instance_id(self) -> str:
        return self._instance_id

    @property
    def enabled(self) -> bool:
        return self._enabled

    async def _probe_self(self) -> bool:
        """Health-Probe gegen das eigene /api/health (Loopback)."""
        if not self._client:
            return True  # Wenn kein HTTP-Loop laeuft, ist der Service selbst der Upstream
        try:
            r = await self._client.get(self._health_url, timeout=3.0)
            if r.status_code == 200:
                payload = r.json()
                return payload.get("status") == "ok"
            return False
        except (httpx.HTTPError, asyncio.TimeoutError):
            return False

    async def _post_heartbeat(self, health_status: str, manifest: dict) -> bool:
        """Sendet einen Heartbeat ans Gateway. Returnt True bei HTTP 2xx."""
        body = {
            "service": _env("SERVICE_BUS_NAME", DEFAULT_NAME),
            "instance_id": self._instance_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "base_url": self._base_url,
            "health_status": health_status,
            "metrics": self.metrics.snapshot(),
            "manifest": manifest,
        }
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        try:
            r = await self._client.post(
                f"{self._gateway_url}/registry/heartbeat",
                json=body,
                headers=headers,
                timeout=4.0,
            )
            if 200 <= r.status_code < 300:
                return True
            logger.warning("Heartbeat HTTP %d: %s", r.status_code, r.text[:200])
            return False
        except (httpx.HTTPError, asyncio.TimeoutError) as e:
            logger.warning("Heartbeat fehlgeschlagen (%s): %s", type(e).__name__, e)
            return False

    async def _deregister(self):
        """Sauberer Shutdown: aus Registry entfernen.

        Hinweis: Das Gateway-Endpunkt akzeptiert `service` + `instance_id`
        als **Query-Params**, nicht als JSON-Body. Falscher Body → 422.
        """
        if not self._client:
            return
        service = _env("SERVICE_BUS_NAME", DEFAULT_NAME)
        headers = {}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        try:
            r = await self._client.post(
                f"{self._gateway_url}/registry/deregister",
                params={"service": service, "instance_id": self._instance_id},
                headers=headers,
                timeout=3.0,
            )
            logger.info("Deregister: HTTP %d", r.status_code)
        except (httpx.HTTPError, asyncio.TimeoutError) as e:
            logger.warning("Deregister fehlgeschlagen: %s", e)

    async def _loop(self):
        """Haupt-Loop: alle N Sekunden Health-Probe + Heartbeat."""
        logger.info(
            "GatewayClient start: instance=%s gateway=%s interval=%ds",
            self._instance_id, self._gateway_url, self._interval,
        )
        manifest = _build_manifest(self._base_url, self._capabilities)
        ok_streak = 0
        err_streak = 0
        try:
            while not self._stopped.is_set():
                # 1. Self-Probe (nur wenn HTTP-Loop aktiv ist -- sonst ueberspringen)
                healthy = await self._probe_self() if self._client else True
                # 2. Heartbeat senden
                sent = await self._post_heartbeat(
                    "healthy" if healthy else "unhealthy",
                    manifest,
                )
                if sent and healthy:
                    ok_streak += 1
                    err_streak = 0
                    if ok_streak == 1 or ok_streak % 12 == 0:  # beim 1. + alle 60s loggen
                        logger.info(
                            "Heartbeat OK: %s health=%s streak=%d",
                            self._instance_id, "healthy" if healthy else "unhealthy", ok_streak,
                        )
                else:
                    err_streak += 1
                    ok_streak = 0
                    logger.warning(
                        "Heartbeat fail streak=%d (healthy=%s sent=%s)",
                        err_streak, healthy, sent,
                    )
                # 3. Warten (mit kooperativem Cancel)
                try:
                    await asyncio.wait_for(self._stopped.wait(), timeout=self._interval)
                except asyncio.TimeoutError:
                    pass
        except asyncio.CancelledError:
            logger.info("GatewayClient cancelled")
            raise
        finally:
            await self._deregister()

    async def start(self):
        """Startet den Heartbeat-Loop als Background-Task."""
        if not self._enabled:
            logger.info("GatewayClient disabled (GATEWAY_REGISTRATION=false)")
            return
        self._client = httpx.AsyncClient()
        self._task = asyncio.create_task(self._loop(), name="gateway-heartbeat")

    async def stop(self):
        """Stoppt den Loop sauber, deregistriert, schliesst die Session."""
        if not self._task:
            return
        self._stopped.set()
        try:
            await asyncio.wait_for(self._task, timeout=self._interval + 2)
        except asyncio.TimeoutError:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self._client:
            await self._client.aclose()
            self._client = None
        logger.info("GatewayClient stopped: %s", self._instance_id)


# ---------------------------------------------------------------------------
# CLI-Modus (fuer Smoke-Tests ohne FastAPI)
# ---------------------------------------------------------------------------

async def _main():
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    client = GatewayClient()
    await client.start()
    try:
        # Läuft bis SIGINT
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig_name in ("SIGINT", "SIGTERM"):
            try:
                loop.add_signal_handler(getattr(__import__("signal"), sig_name), stop.set)
            except (NotImplementedError, RuntimeError):
                pass  # Windows: keine Signal-Handler
        await stop.wait()
    finally:
        await client.stop()


if __name__ == "__main__":
    asyncio.run(_main())