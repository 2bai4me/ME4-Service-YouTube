"""ZMQ REQ/REP Server — Hauptservice-Schnittstelle (MCP-konform)."""
from __future__ import annotations

import asyncio
import json
import time as _time
from typing import Any, Optional

import zmq
import zmq.asyncio

from app.auth import verify_zmq_key
from app.config import settings
from app.loadbalancer import WorkerPool
from app.logging_config import get_logger
from app.models import ProcessRequest

logger = get_logger(__name__)


class ZMQService:
    """MCP-konformer ZMQ REQ/REP Server für den Hauptservice."""

    def __init__(self, pool: WorkerPool, port: Optional[int] = None):
        self.pool = pool
        self.port = port or settings.zmq_port
        self._ctx: Optional[zmq.asyncio.Context] = None
        self._socket: Optional[zmq.asyncio.Socket] = None
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._start_time = _time.time()

    async def start(self) -> None:
        """Startet den ZMQ-Listener."""
        self._ctx = zmq.asyncio.Context()
        self._socket = self._ctx.socket(zmq.REP)
        self._socket.setsockopt(zmq.LINGER, 0)
        self._socket.bind(f"tcp://*:{self.port}")
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info("ME4-YOUTUBE ZMQ listening on tcp://*:%d", self.port)

    async def stop(self) -> None:
        """Stoppt den ZMQ-Listener."""
        self._running = False
        if self._task:
            self._task.cancel()
        if self._socket:
            self._socket.close()
        if self._ctx:
            self._ctx.term()
        logger.info("ME4-YOUTUBE ZMQ stopped")

    async def _loop(self) -> None:
        """Hauptloop."""
        try:
            while self._running:
                msg = await self._socket.recv_json()  # type: ignore[union-attr]
                resp = await self._handle(msg)
                await self._socket.send_json(resp)  # type: ignore[union-attr]
        except asyncio.CancelledError:
            pass
        except Exception as e:  # noqa: BLE001
            logger.exception("ZMQ loop crashed: %s", e)

    async def _handle(self, msg: dict[str, Any]) -> dict[str, Any]:
        """Verarbeitet eine MCP-Nachricht."""
        method = msg.get("method", "")
        rid = msg.get("id", "0")
        if method == "initialize":
            return self._init(rid, msg.get("params", {}))
        if method == "tools/list":
            return self._tools_list(rid)
        if method == "tools/call":
            return await self._tools_call(rid, msg.get("params", {}))
        return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": f"unknown method: {method}"}}

    def _init(self, rid: Any, params: dict) -> dict[str, Any]:
        """MCP-Initialize-Handshake."""
        return {
            "jsonrpc": "2.0", "id": rid,
            "result": {
                "protocolVersion": "2024-11-05",
                "serverInfo": {
                    "name": settings.service_id,
                    "version": settings.service_version,
                },
                "capabilities": {"tools": {}},
            },
        }

    def _tools_list(self, rid: Any) -> dict[str, Any]:
        """Liefert Tool-Liste."""
        tools = [
            {"name": "ping", "description": "Service-Ping (public)", "inputSchema": {"type": "object", "properties": {}}},
            {"name": "get_manifest", "description": "UI-Manifest (public)", "inputSchema": {"type": "object", "properties": {}}},
            {"name": "health", "description": "Detaillierter Service-Status (public)", "inputSchema": {"type": "object", "properties": {}}},
            {"name": "get_metadata", "description": "YouTube Metadaten/Beschreibung", "inputSchema": {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]}},
            {"name": "get_transcript", "description": "YouTube Transkript", "inputSchema": {"type": "object", "properties": {"url": {"type": "string"}, "language": {"type": "string"}}, "required": ["url"]}},
            {"name": "get_comments", "description": "YouTube Kommentare", "inputSchema": {"type": "object", "properties": {"url": {"type": "string"}, "max_comments": {"type": "integer"}}, "required": ["url"]}},
            {"name": "download", "description": "YouTube Video-Download", "inputSchema": {"type": "object", "properties": {"url": {"type": "string"}, "audio_only": {"type": "boolean"}, "format": {"type": "string"}}, "required": ["url"]}},
            {"name": "process", "description": "Vollständige YouTube-Verarbeitung", "inputSchema": {"type": "object", "properties": {
                "url": {"type": "string"}, "download": {"type": "boolean"},
                "include_description": {"type": "boolean"}, "include_transcript": {"type": "boolean"},
                "include_comments": {"type": "boolean"}, "language": {"type": "string"},
                "max_comments": {"type": "integer"},
            }, "required": ["url"]}},
            {"name": "trigger_sm_produce", "description": "SM-Producer anstoßen", "inputSchema": {"type": "object", "properties": {
                "url": {"type": "string"}, "transcript": {"type": "string"},
                "language": {"type": "string"}, "workflow": {"type": "string"},
            }, "required": ["url"]}},
            {"name": "get_status_snapshot", "description": "Live-Status aller Jobs", "inputSchema": {"type": "object", "properties": {}}},
            {"name": "shutdown", "description": "Service herunterfahren", "inputSchema": {"type": "object", "properties": {}}},
        ]
        return {"jsonrpc": "2.0", "id": rid, "result": {"tools": tools}}

    async def _tools_call(self, rid: Any, params: dict) -> dict[str, Any]:
        """Tool-Aufruf dispatchen."""
        name = params.get("name", "")
        args = params.get("arguments", {}) or {}

        if name not in {"ping", "get_manifest", "health", "get_status_snapshot", "tools/list"}:
            try:
                verify_zmq_key(args)
            except Exception as e:  # noqa: BLE001
                return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32001, "message": str(e)}}

        handlers = {
            "ping": self._h_ping,
            "get_manifest": self._h_manifest,
            "health": self._h_health,
            "get_status_snapshot": self._h_status,
            "get_metadata": self._h_metadata,
            "get_transcript": self._h_transcript,
            "get_comments": self._h_comments,
            "download": self._h_download,
            "process": self._h_process,
            "trigger_sm_produce": self._h_sm_produce,
            "shutdown": self._h_shutdown,
        }
        h = handlers.get(name)
        if not h:
            return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32602, "message": f"unknown tool: {name}"}}
        try:
            result = h(rid, args)
            # Falls Handler async ist, awaiten
            if hasattr(result, "__await__"):
                result = await result
            return {"jsonrpc": "2.0", "id": rid, "result": result}
        except Exception as e:  # noqa: BLE001
            logger.exception("tool %s failed", name)
            return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32099, "message": str(e)}}

    # === Handlers ===
    def _h_ping(self, rid: Any, args: dict) -> dict:
        return {"content": [{"type": "text", "text": json.dumps({"status": "ok", "service": settings.service_id, "version": settings.service_version})}]}

    def _h_manifest(self, rid: Any, args: dict) -> dict:
        return {"content": [{"type": "text", "text": json.dumps(self._manifest(), ensure_ascii=False)}]}

    def _h_health(self, rid: Any, args: dict) -> dict:
        pool_status = self.pool.status()
        return {"content": [{"type": "text", "text": json.dumps({
            "status": "ok",
            "service": settings.service_id,
            "version": settings.service_version,
            "uptime_sec": _time.time() - self._start_time,
            "workers_active": pool_status["alive"],
            "workers_total": pool_status["size"],
            "loadbalancer": pool_status,
        })}]}

    def _h_status(self, rid: Any, args: dict) -> dict:
        from app.status_tracker import status_tracker
        return {"content": [{"type": "text", "text": json.dumps(status_tracker.snapshot(), ensure_ascii=False)}]}

    async def _h_metadata(self, rid: Any, args: dict) -> dict:
        from app.extractor import extract_video_id, get_video_metadata
        vid = extract_video_id(args.get("url", ""))
        if not vid:
            return self._err("invalid URL")
        return {"content": [{"type": "text", "text": json.dumps(get_video_metadata(vid), ensure_ascii=False)}]}

    async def _h_transcript(self, rid: Any, args: dict) -> dict:
        from app.extractor import extract_video_id
        from app.transcriber import get_transcript
        vid = extract_video_id(args.get("url", ""))
        if not vid:
            return self._err("invalid URL")
        lang = args.get("language", "de")
        return {"content": [{"type": "text", "text": json.dumps(get_transcript(vid, [lang, "en"]), ensure_ascii=False)}]}

    async def _h_comments(self, rid: Any, args: dict) -> dict:
        from app.extractor import extract_video_id, get_video_comments
        vid = extract_video_id(args.get("url", ""))
        if not vid:
            return self._err("invalid URL")
        mc = int(args.get("max_comments", 100))
        return {"content": [{"type": "text", "text": json.dumps(get_video_comments(vid, mc), ensure_ascii=False)}]}

    async def _h_download(self, rid: Any, args: dict) -> dict:
        from app.downloader import download_video
        from app.extractor import extract_video_id
        vid = extract_video_id(args.get("url", ""))
        if not vid:
            return self._err("invalid URL")
        result = await download_video(
            video_id=vid,
            audio_only=bool(args.get("audio_only", False)),
            format_selector=args.get("format"),
        )
        return {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}]}

    async def _h_process(self, rid: Any, args: dict) -> dict:
        """Leitet process an den Loadbalancer/Worker-Pool weiter."""
        import httpx
        try:
            worker = self.pool.select_worker()
        except Exception as e:  # noqa: BLE001
            return self._err(str(e))
        url = f"http://{worker.host}:{worker.port}/process"
        async with httpx.AsyncClient(timeout=settings.request_timeout_sec) as c:
            r = await c.post(url, json=args)
            r.raise_for_status()
            return {"content": [{"type": "text", "text": json.dumps(r.json(), ensure_ascii=False)}]}

    async def _h_sm_produce(self, rid: Any, args: dict) -> dict:
        from app.sm_producer_client import SMProducerClient
        client = SMProducerClient()
        result = await client.trigger_produce(
            video_url=args.get("url", ""),
            transcript=args.get("transcript", ""),
            language=args.get("language", "de"),
            workflow=args.get("workflow", "default"),
        )
        return {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}]}

    async def _h_shutdown(self, rid: Any, args: dict) -> dict:
        asyncio.create_task(self._graceful_shutdown())
        return {"content": [{"type": "text", "text": json.dumps({"status": "shutting_down"})}]}

    async def _graceful_shutdown(self) -> None:
        await asyncio.sleep(0.5)
        await self.pool.stop()
        await self.stop()

    def _manifest(self) -> dict:
        """Return the Baustein-compatible service manifest.

        Includes the full `ServiceDefinition` shape (greeting, pipeline,
        functions, buttons, …) so the ME4-UI Baustein can render the
        service without any pre-registration.  Buttons carry the full
        binding info (path, method, bodyTemplate, function, stage,
        produces) — the Baustein uses this to render the 4-button bar
        (the 4 core data-extraction functions) and to wire the pipeline.
        """
        return {
            # ─── service identity ────────────────────────────────────────
            "id": settings.service_id,
            "name": settings.service_name,
            "subtitle": "YouTube → Captions → Sections → Slides",
            "description": (
                "YouTube content extraction service — fetch metadata, "
                "transcripts, comments, download media, run the full process "
                "pipeline, or hand off to the SM-Producer orchestrator."
            ),
            "apiProxyBase": f"http://localhost:{settings.http_port}",
            "version": settings.service_version,
            "service_type": "MCP-Server + ZMQ + HTTP + Framie",
            "category": "content_extraction",
            "languages": ["de", "en"],

            # ─── Baustein contract ───────────────────────────────────────
            "kind": "service",
            "greeting": (
                f"👋 Willkommen beim Service {settings.service_name}\n"
                f"Version: {settings.service_version}\n"
                "\n"
                "Dieser Service lädt YouTube-Inhalte über **vier "
                "Top-Level-Funktionen**. Klicke oben einen Button, um die "
                "zugehörige Pipeline zu starten."
            ),
            "pipeline": [
                {"id": "parse_url",         "name": "Parse URL",        "phase": 0},
                {"id": "fetch_metadata",    "name": "Fetch Metadata",   "phase": 1, "requires": ["parse_url"]},
                {"id": "fetch_captions",    "name": "Fetch Captions",   "phase": 1, "requires": ["parse_url"]},
                {"id": "fetch_comments",    "name": "Fetch Comments",   "phase": 1, "requires": ["parse_url"]},
                {"id": "download_video",    "name": "Download Video",   "phase": 1, "requires": ["parse_url"], "produces": {"kind": "download"}},
                {"id": "convert_audio",     "name": "Convert Audio",    "phase": 2, "requires": ["download_video"]},
                {"id": "split_sections",    "name": "Split Sections",   "phase": 2, "requires": ["fetch_captions"]},
                {"id": "build_slides",      "name": "Build Slides",     "phase": 3, "requires": ["split_sections"]},
                {"id": "export_package",    "name": "Export Package",   "phase": 4, "requires": ["build_slides"], "produces": {"kind": "download"}},
                {"id": "forward_smproducer", "name": "Forward to SM-Producer", "phase": 0},
            ],
            "functions": [
                {"id": "metadata",   "name": "Get Metadata",            "description": "Extract video title, channel, duration, tags.", "stages": ["parse_url", "fetch_metadata"],
                 "steps": [
                     {"id": "call_url",   "name": "URL aufrufen",         "icon": "🔗", "description": "Service prüft die YouTube-URL"},
                     {"id": "fetch_data", "name": "Daten abrufen",       "icon": "📥", "description": "yt-dlp extrahiert Video-Informationen"},
                     {"id": "save_data",  "name": "Daten speichern",      "icon": "💾", "description": "Ergebnis als JSON+MD auf Platte schreiben"}
                 ]},
                {"id": "transcript", "name": "Get Transcript",          "description": "Pull captions or auto-generated transcript.", "stages": ["parse_url", "fetch_captions"],
                 "steps": [
                     {"id": "call_url",     "name": "URL aufrufen",         "icon": "🔗"},
                     {"id": "fetch_captions", "name": "Captions abrufen",  "icon": "📝"},
                     {"id": "save_data",    "name": "Daten speichern",      "icon": "💾"}
                 ]},
                {"id": "comments",   "name": "Get Comments",            "description": "Pull the top comments.", "stages": ["parse_url", "fetch_comments"],
                 "steps": [
                     {"id": "call_url",   "name": "URL aufrufen",         "icon": "🔗"},
                     {"id": "fetch_comments","name": "Kommentare laden",   "icon": "💬"},
                     {"id": "save_data",  "name": "Daten speichern",      "icon": "💾"}
                 ]},
                {"id": "download",   "name": "Download",                "description": "Save the video (and optionally the audio).", "stages": ["parse_url", "download_video", "convert_audio"],
                 "steps": [
                     {"id": "call_url",   "name": "URL aufrufen",         "icon": "🔗"},
                     {"id": "download",   "name": "Video herunterladen",  "icon": "📥"},
                     {"id": "convert",    "name": "Format konvertieren",   "icon": "🔄"},
                     {"id": "save_file",  "name": "Datei speichern",      "icon": "💾"}
                 ]},
                {"id": "process",    "name": "Process (full pipeline)", "description": "Metadata → Captions → Split → Slides → Export deck.", "stages": ["parse_url", "fetch_metadata", "fetch_captions", "split_sections", "build_slides", "export_package"],
                 "steps": [
                     {"id": "call_url",   "name": "URL aufrufen",         "icon": "🔗"},
                     {"id": "fetch",     "name": "Metadaten + Transkript abrufen", "icon": "📥"},
                     {"id": "split",     "name": "Sektionen splitten",   "icon": "✂️"},
                     {"id": "slides",    "name": "Slides bauen",         "icon": "📊"},
                     {"id": "export",    "name": "Slides exportieren",   "icon": "📤"},
                     {"id": "save_data",  "name": "Daten speichern",      "icon": "💾"}
                 ]},
                {"id": "smproducer", "name": "Trigger SM-Producer",     "description": "Hand the URL off to the orchestrator.", "stages": ["forward_smproducer"],
                 "steps": [
                     {"id": "call_url",     "name": "URL aufrufen",         "icon": "🔗"},
                     {"id": "forward",      "name": "An SM-Producer senden","icon": "📤"},
                     {"id": "save_data",    "name": "Antwort speichern",    "icon": "💾"}
                 ]}
            ],
            "buttons": [
                {"slot": 0, "label": "Get Metadata",       "function": "metadata",   "target": {"method": "POST", "path": "/api/metadata",   "bodyTemplate": {"url": ""}}},
                {"slot": 1, "label": "Get Transcript",     "function": "transcript", "target": {"method": "POST", "path": "/api/transcript", "bodyTemplate": {"url": "", "language": "de"}}},
                {"slot": 2, "label": "Get Comments",       "function": "comments",   "target": {"method": "POST", "path": "/api/comments",   "bodyTemplate": {"url": "", "max_comments": 100}}},
                {"slot": 3, "label": "Download",           "function": "download",   "target": {"method": "POST", "path": "/api/download",   "bodyTemplate": {"url": "", "audio_only": False}}},
            ],

            # ─── legacy / informational ──────────────────────────────────
            "capabilities": [
                "video_download",
                "metadata_extraction",
                "transcript_extraction",
                "comments_extraction",
                "translation",
                "load_balancing",
                "live_status_stream",
                "sm_producer_integration",
            ],
            "actions": [
                {"id": "get_metadata", "label": "YouTube Metadaten & Beschreibung abrufen"},
                {"id": "get_transcript", "label": "YouTube Transkript extrahieren"},
                {"id": "get_comments", "label": "YouTube Kommentare laden"},
                {"id": "download", "label": "YouTube Video/Audio herunterladen"},
                {"id": "process", "label": "Vollständige YouTube-Verarbeitung"},
                {"id": "trigger_sm_produce", "label": "SM-Producer-Pipeline anstoßen"},
            ],
            "mcp": {
                "command": "python",
                "args": ["main.py"],
                "env": {"ME4_YOUTUBE_ZMQ_PORT": str(settings.zmq_port)},
            },
            "loadbalancer": {
                "zmq_port": settings.loadbalancer_zmq_port,
                "pool_size": settings.worker_count,
                "strategy": settings.loadbalancer_strategy,
            },
            "ports": {
                "http": settings.http_port,
                "zmq": settings.zmq_port,
                "wssp15": settings.wssp15_port,
                "loadbalancer_zmq": settings.loadbalancer_zmq_port,
            },
            "health_endpoint": f"http://localhost:{settings.http_port}/api/health",
            "framie_endpoint": f"http://localhost:{settings.http_port}/ui/index.html",
        }

    def _err(self, msg: str) -> dict:
        return {"content": [{"type": "text", "text": json.dumps({"status": "error", "message": msg})}]}
