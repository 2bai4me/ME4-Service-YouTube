"""Pipeline-Orchestrator — koordiniert die Verarbeitung in einem Worker."""
from __future__ import annotations

import time
from typing import Any, Optional

from app.downloader import download_video
from app.extractor import get_video_comments, get_video_metadata
from app.logging_config import get_logger
from app.models import ProcessRequest, ProcessResponse
from app.status_tracker import status_tracker
from app.transcriber import get_transcript, transcript_to_plain_text

logger = get_logger(__name__)


class Orchestrator:
    """Führt den kompletten YouTube-Pipeline-Lauf für einen Worker aus."""

    def __init__(self, worker_id: str):
        self.worker_id = worker_id

    async def process(
        self,
        request: ProcessRequest,
        progress_callback=None,
    ) -> ProcessResponse:
        """Vollständige Verarbeitung einer YouTube-URL."""
        from app.extractor import extract_video_id

        video_id = extract_video_id(request.url)
        if not video_id:
            return ProcessResponse(
                status="error", video_id="", url=request.url,
                error=f"invalid URL: {request.url}",
            )

        job = status_tracker.create_job(request.url, worker_id=self.worker_id)
        start = time.time()

        try:
            await status_tracker.update(
                job.job_id, state="running", step="metadata",
                progress=0.1, message="Hole Metadaten…",
                worker_id=self.worker_id,
            )

            # === 1. METADATA / DESCRIPTION ===
            description = None
            metadata = None
            if request.include_description:
                try:
                    metadata = get_video_metadata(video_id)
                    description = metadata.get("description", "")
                except Exception as e:  # noqa: BLE001
                    logger.warning("metadata failed: %s", e)
                    metadata = {"error": str(e)}
                if progress_callback:
                    progress_callback("metadata", 0.25)

            # === 2. TRANSCRIPT ===
            transcript = None
            transcript_text = ""
            if request.include_transcript:
                await status_tracker.update(
                    job.job_id, step="transcript",
                    progress=0.4, message="Hole Transkript…",
                )
                try:
                    transcript = get_transcript(
                        video_id,
                        languages=[request.language, "en"],
                    )
                    transcript_text = transcript_to_plain_text(transcript)
                except Exception as e:  # noqa: BLE001
                    logger.warning("transcript failed: %s", e)
                    transcript = {"error": str(e)}
                if progress_callback:
                    progress_callback("transcript", 0.55)

            # === 3. DOWNLOAD ===
            download_path = None
            if request.download:
                await status_tracker.update(
                    job.job_id, step="download",
                    progress=0.7, message="Lade Video herunter…",
                )

                def _cb(d: dict) -> None:
                    # yt-dlp progress hook → status_tracker
                    pct = d.get("percent", "0%").replace("%", "").strip()
                    try:
                        p = float(pct) / 100.0
                    except ValueError:
                        p = 0.7
                    status_tracker._publish_sync(  # type: ignore[attr-defined]
                        {"event": "download.progress", "data": d, "job_id": job.job_id},
                    )

                try:
                    res = await download_video(
                        video_id=video_id,
                        audio_only=request.audio_only,
                        format_selector=request.download_format,
                        progress_callback=_cb,
                    )
                    download_path = res.get("path")
                except Exception as e:  # noqa: BLE001
                    logger.warning("download failed: %s", e)
                    download_path = f"error: {e}"
                if progress_callback:
                    progress_callback("download", 0.9)

            # === 4. COMMENTS ===
            comments = None
            if request.include_comments and request.max_comments > 0:
                await status_tracker.update(
                    job.job_id, step="comments",
                    progress=0.95, message="Hole Kommentare…",
                )
                try:
                    comments_data = get_video_comments(video_id, request.max_comments)
                    comments = comments_data.get("comments", [])
                except Exception as e:  # noqa: BLE001
                    logger.warning("comments failed: %s", e)
                    comments = []

            duration = time.time() - start
            response = ProcessResponse(
                status="ok",
                video_id=video_id,
                url=request.url,
                description=description,
                metadata=metadata,
                transcript=transcript,
                comments=comments,
                download_path=download_path,
                duration_sec=round(duration, 2),
                worker_id=self.worker_id,
            )
            await status_tracker.finish(
                job.job_id,
                result=response.model_dump(),
            )
            return response

        except Exception as e:
            logger.exception("orchestrator failed")
            await status_tracker.finish(job.job_id, error=str(e))
            return ProcessResponse(
                status="error", video_id=video_id, url=request.url,
                error=str(e), duration_sec=time.time() - start,
                worker_id=self.worker_id,
            )
