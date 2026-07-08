"""YouTube Video-Download via yt-dlp."""
from __future__ import annotations

import asyncio
import os
import re
from pathlib import Path
from typing import Any, Optional

import yt_dlp

from app.config import settings
from app.exceptions import DownloadError, InvalidURLError
from app.extractor import extract_video_id
from app.logging_config import get_logger

logger = get_logger(__name__)

_SAFE_TITLE = re.compile(r"[^A-Za-z0-9._-]+")


def _safe_filename(title: str, ext: str, max_len: int = 80) -> str:
    """Baut einen sicheren Dateinamen aus einem Video-Titel."""
    base = _SAFE_TITLE.sub("_", title or "video").strip("_")
    if len(base) > max_len:
        base = base[:max_len]
    return f"{base}.{ext.lstrip('.')}"


async def download_video(
    video_id: str,
    output_dir: Optional[str] = None,
    audio_only: bool = False,
    format_selector: Optional[str] = None,
    progress_callback=None,
) -> dict[str, Any]:
    """Lädt ein YouTube-Video herunter. Gibt Pfad + Metadaten zurück."""
    if not video_id or len(video_id) != 11:
        raise InvalidURLError(f"invalid video id: {video_id}")

    out_dir = Path(output_dir or settings.download_dir) / video_id
    out_dir.mkdir(parents=True, exist_ok=True)

    if audio_only:
        fmt = "bestaudio[ext=m4a]/bestaudio/best"
        ext = "m4a"
    else:
        fmt = format_selector or settings.download_dir and settings.download_dir or "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best"
        # Default video format
        fmt = format_selector or "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best"
        ext = "mp4"

    def _hook(d: dict) -> None:
        if progress_callback and d.get("status") == "downloading":
            try:
                pct = d.get("_percent_str", "0%").strip()
                speed = d.get("_speed_str", "").strip()
                eta = d.get("_eta_str", "").strip()
                progress_callback({
                    "status": "downloading",
                    "percent": pct,
                    "speed": speed,
                    "eta": eta,
                    "filename": d.get("filename", ""),
                })
            except Exception:  # noqa: BLE001
                pass

    opts: dict[str, Any] = {
        "format": fmt,
        "outtmpl": str(out_dir / "%(title).80s.%(ext)s"),
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "merge_output_format": ext if not audio_only else None,
        "progress_hooks": [_hook],
    }
    if audio_only:
        opts["postprocessors"] = [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "m4a",
        }]

    url = f"https://www.youtube.com/watch?v={video_id}"
    try:
        loop = asyncio.get_running_loop()
        # yt-dlp ist synchron — in Thread ausführen, damit der Event-Loop nicht blockiert
        info = await loop.run_in_executor(None, _download_sync, url, opts)
    except yt_dlp.utils.DownloadError as e:
        raise DownloadError(f"download failed: {e}") from e
    except Exception as e:
        logger.exception("download crashed")
        raise DownloadError(f"download crashed: {e}") from e

    # Tatsächlichen Pfad ermitteln
    final_path = info.get("requested_downloads", [{}])[0].get("filepath") if info.get("requested_downloads") else None
    if not final_path:
        # Fallback: erstes File im Verzeichnis
        files = sorted(out_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
        final_path = str(files[0]) if files else None

    if final_path and os.path.exists(final_path):
        size_mb = os.path.getsize(final_path) / 1024 / 1024
        if size_mb > settings.max_download_size_mb:
            os.remove(final_path)
            raise DownloadError(f"file exceeds max size {settings.max_download_size_mb}MB")

    return {
        "success": True,
        "video_id": video_id,
        "path": final_path,
        "directory": str(out_dir),
        "title": info.get("title", ""),
        "duration_sec": info.get("duration") or 0,
        "size_mb": round(os.path.getsize(final_path) / 1024 / 1024, 2) if final_path and os.path.exists(final_path) else 0,
        "format_id": info.get("format_id", ""),
    }


def _download_sync(url: str, opts: dict) -> dict:
    """Synchroner Download (für run_in_executor)."""
    with yt_dlp.YoutubeDL(opts) as ydl:
        return ydl.extract_info(url, download=True)
