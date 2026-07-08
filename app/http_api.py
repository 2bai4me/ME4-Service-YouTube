"""HTTP REST API (FastAPI) — öffentliche Schnittstelle + Framie-Status-Stream.

Erkennt das `ME4-UI / ME4-UI-Baustein`-Protokoll: wenn ein Endpoint eine
YouTube-URL braucht und keine bekommt, antwortet er mit
`{ "awaitInput": { title, description?, fields: [...] } }` statt mit HTTP 400.
Der Baustein zeigt dann ein Inline-Formular im Chat an, der User gibt die
URL ein, der Baustein feuert den Button erneut mit `{ input: { url } }`.

Funktions-Ergebnisse werden lokal unter
``data/sessions/<session_id>/<NN-function>/{result.json,result.md}``
abgelegt.  Die HTTP-Response enthält die Pfade; das Baustein zeigt im
Chat nur den Pfad-Hinweis, nicht die vollen Daten.
"""
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any, Optional

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.auth import verify_http_key
from app.config import settings
from app.loadbalancer import WorkerPool
from app.logging_config import get_logger
from app.models import ProcessRequest
from app.session_store import write_result
from app.status_tracker import status_tracker
from app.zmq_service import ZMQService

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# ME4-UI ↔ ME4-YouTube contract helpers
# ---------------------------------------------------------------------------

def _await_input(
    title: str,
    description: str,
    fields: list[dict[str, Any]],
) -> dict[str, Any]:
    """Return the Baustein `awaitInput` envelope for a missing input."""
    return {
        "awaitInput": {
            "title": title,
            "description": description,
            "fields": fields,
        }
    }


_URL_FIELD = [
    {
        "name": "url",
        "label": "YouTube URL",
        "type": "url",
        "required": True,
        "placeholder": "https://www.youtube.com/watch?v=…",
    }
]


def _needs_url(req: dict[str, Any]) -> bool:
    """True when the request is missing a usable YouTube URL."""
    from app.extractor import extract_video_id
    url = req.get("url") or ""
    return not extract_video_id(url)


def _summary(function_name: str, result: dict[str, Any]) -> dict[str, Any]:
    """Build a compact response for the Baustein chat notification.

    Returns only:
      - the directory the result was saved into
      - a one-line human summary
      - a couple of headline fields the user might want to glance at
    The full result lives in <dir>/result.json and <dir>/result.md.
    """
    func_dir = result.get("_dir", "")
    headline = {
        k: v for k, v in result.items()
        if k in {"success", "title", "channel", "snippet_count", "count", "file"}
        and v not in (None, "", [])
    }
    return {
        "filesSavedTo": func_dir,
        "jsonPath": str(Path(func_dir) / "result.json") if func_dir else None,
        "mdPath": str(Path(func_dir) / "result.md") if func_dir else None,
        "headline": headline,
        "function": function_name,
    }


# ---------------------------------------------------------------------------


def build_app(pool: WorkerPool, zmq_service: ZMQService) -> FastAPI:
    """Baut die FastAPI-App inkl. Framie-Status-Stream."""
    app = FastAPI(
        title=settings.service_name,
        version=settings.service_version,
        description="YouTube Content Extraction Service — Download, Metadata, Transcript, Comments",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/")
    async def root():
        return {
            "service": settings.service_id,
            "version": settings.service_version,
            "framie": f"/ui/index.html",
            "api_docs": "/docs",
        }

    @app.get("/api/health")
    async def health():
        ps = pool.status()
        return {
            "status": "ok",
            "service": settings.service_id,
            "version": settings.service_version,
            "uptime_sec": time.time() - _app_start_time,
            "workers_active": ps["alive"],
            "workers_total": ps["size"],
            "loadbalancer": ps,
        }

    @app.get("/api/manifest")
    async def manifest():
        return zmq_service._manifest()

    @app.get("/api/status")
    async def status():
        return status_tracker.snapshot()

    @app.get("/api/framie/stream")
    async def framie_stream(request: Request):
        """SSE-Stream für Framie-UI — direkter Live-Status."""
        async def event_gen():
            q = await status_tracker.subscribe()
            try:
                # Initiales Snapshot
                yield f"event: snapshot\ndata: {json.dumps(status_tracker.snapshot(), ensure_ascii=False)}\n\n"
                while True:
                    if await request.is_disconnected():
                        break
                    try:
                        evt = await asyncio.wait_for(q.get(), timeout=15)
                        yield f"event: {evt.get('event', 'message')}\ndata: {json.dumps(evt.get('data', {}), ensure_ascii=False)}\n\n"
                    except asyncio.TimeoutError:
                        yield ": keepalive\n\n"
            finally:
                await status_tracker.unsubscribe(q)
        return StreamingResponse(event_gen(), media_type="text/event-stream")

    @app.post("/api/process", dependencies=[Depends(verify_http_key)])
    async def process(req: ProcessRequest):
        """Direkt-Verarbeitung: leitet an Worker-Pool weiter.

        Speichert das Ergebnis automatisch in:
          - SQLite (app/persistence.py) fuer strukturierte Daten
          - data/{job_id}.json fuer die vollstaendige Response
        """
        import httpx
        import uuid
        from app.persistence import save_result

        # Eindeutige Job-ID erzeugen
        job_id = f"job_{int(time.time())}_{uuid.uuid4().hex[:8]}"

        try:
            worker = pool.select_worker()
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=503, detail=str(e))
        url = f"http://{worker.host}:{worker.port}/process"
        try:
            async with httpx.AsyncClient(timeout=settings.request_timeout_sec) as c:
                r = await c.post(url, json=req.model_dump())
                r.raise_for_status()
                response_data = r.json()
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e))

        # Persistierung: JSON + SQLite
        try:
            persisted = save_result(
                job_id=job_id,
                url=req.url,
                response=response_data,
            )
            response_data["_persistence"] = persisted
        except Exception as e:  # noqa: BLE001
            logger.warning("Persistierung fehlgeschlagen: %s", e)
            response_data["_persistence"] = {"error": str(e)}

        return JSONResponse(content=response_data)

    @app.get("/api/results")
    async def list_results(limit: int = 20):
        """Listet die letzten Process-Ergebnisse aus der SQLite-DB."""
        from app.persistence import list_results, get_stats
        return JSONResponse(content={
            "stats": get_stats(),
            "results": list_results(limit=limit),
        })

    @app.get("/api/results/{job_id}")
    async def get_result(job_id: str):
        """Holt ein einzelnes Ergebnis."""
        from app.persistence import get_result
        result = get_result(job_id)
        if not result:
            raise HTTPException(status_code=404, detail="not found")
        return JSONResponse(content=result)

    # -----------------------------------------------------------------------
    # Function endpoints — each one speaks the awaitInput protocol
    # -----------------------------------------------------------------------

    @app.post("/api/metadata", dependencies=[Depends(verify_http_key)])
    async def metadata(req: dict[str, Any]):
        from app.extractor import extract_video_id, get_video_metadata
        if _needs_url(req):
            return _await_input(
                "🎬 YouTube-URL eingeben",
                "Der Service braucht eine YouTube-URL, um die Metadaten zu extrahieren.",
                _URL_FIELD,
            )
        vid = extract_video_id(req["url"])
        try:
            result = get_video_metadata(vid)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=400, detail=str(e))
        sid = req.get("sessionId") or ""
        result = write_result(sid, "get-metadata", result, request=req)
        return _summary("get-metadata", result)

    @app.post("/api/transcript", dependencies=[Depends(verify_http_key)])
    async def transcript(req: dict[str, Any]):
        from app.extractor import extract_video_id
        from app.transcriber import get_transcript
        if _needs_url(req):
            return _await_input(
                "📝 YouTube-URL für das Transkript",
                "Welches Transkript soll geholt werden?",
                _URL_FIELD + [
                    {
                        "name": "language",
                        "label": "Sprache (optional)",
                        "type": "text",
                        "defaultValue": "de",
                        "placeholder": "de",
                    }
                ],
            )
        vid = extract_video_id(req["url"])
        try:
            result = get_transcript(vid, [req.get("language", "de"), "en"])
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=400, detail=str(e))
        sid = req.get("sessionId") or ""
        result = write_result(sid, "get-transcript", result, request=req)
        return _summary("get-transcript", result)

    @app.post("/api/comments", dependencies=[Depends(verify_http_key)])
    async def comments(req: dict[str, Any]):
        from app.extractor import extract_video_id, get_video_comments
        if _needs_url(req):
            return _await_input(
                "💬 YouTube-URL für die Kommentare",
                "Welches Video-Kommentarfeld soll geladen werden?",
                _URL_FIELD + [
                    {
                        "name": "max_comments",
                        "label": "Anzahl Kommentare",
                        "type": "number",
                        "defaultValue": 100,
                    }
                ],
            )
        vid = extract_video_id(req["url"])
        try:
            result = get_video_comments(vid, int(req.get("max_comments", 100)))
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=400, detail=str(e))
        sid = req.get("sessionId") or ""
        result = write_result(sid, "get-comments", result, request=req)
        return _summary("get-comments", result)

    @app.post("/api/download", dependencies=[Depends(verify_http_key)])
    async def download(req: dict[str, Any]):
        from app.downloader import download_video
        from app.extractor import extract_video_id
        if _needs_url(req):
            return _await_input(
                "💾 YouTube-Video herunterladen",
                "Welches Video in welchem Format soll heruntergeladen werden?",
                _URL_FIELD + [
                    {
                        "name": "audio_only",
                        "label": "Nur Audio (mp3)?",
                        "type": "checkbox",
                        "defaultValue": False,
                    },
                    {
                        "name": "format",
                        "label": "Format-Selector (optional)",
                        "type": "text",
                        "placeholder": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best",
                    },
                ],
            )
        vid = extract_video_id(req["url"])
        try:
            result = await download_video(
                video_id=vid,
                audio_only=bool(req.get("audio_only", False)),
                format_selector=req.get("format"),
            )
            if result.get("path"):
                import os
                result["file"] = os.path.basename(result["path"])
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e))
        sid = req.get("sessionId") or ""
        result = write_result(sid, "download", result, request=req)
        return _summary("download", result)

    @app.post("/api/sm-produce", dependencies=[Depends(verify_http_key)])
    async def sm_produce(req: dict[str, Any]):
        from app.sm_producer_client import SMProducerClient
        if _needs_url(req):
            return _await_input(
                "🎼 An SM-Producer übergeben",
                "Welches Video soll an die SM-Producer-Pipeline übergeben werden?",
                _URL_FIELD,
            )
        client = SMProducerClient()
        try:
            result = await client.trigger_produce(
                video_url=req["url"],
                transcript=req.get("transcript", ""),
                language=req.get("language", "de"),
                workflow=req.get("workflow", "default"),
                metadata=req.get("metadata"),
            )
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=502, detail=f"SM-Producer: {e}")
        sid = req.get("sessionId") or ""
        result = write_result(sid, "trigger-sm-produce", result, request=req)
        return _summary("trigger-sm-produce", result)

    # Framie-UI statisch ausliefern
    try:
        app.mount("/ui", StaticFiles(directory="static", html=True), name="framie")
    except Exception as e:  # noqa: BLE001
        logger.warning("Framie-UI nicht mountbar: %s", e)

    return app


_app_start_time = time.time()
