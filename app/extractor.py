"""YouTube Video-ID, Metadaten, Kommentare via yt-dlp."""
from __future__ import annotations

import json
import re
from typing import Any, Optional

import yt_dlp

from app.exceptions import (
    CommentsUnavailableError,
    InvalidURLError,
    VideoNotFoundError,
)
from app.logging_config import get_logger

logger = get_logger(__name__)

# YouTube-URL Patterns
_URL_PATTERNS = [
    r"(?:https?://)?(?:www\.|m\.)?youtube\.com/watch\?v=([\w-]{11})",
    r"(?:https?://)?(?:www\.)?youtu\.be/([\w-]{11})",
    r"(?:https?://)?(?:www\.)?youtube\.com/shorts/([\w-]{11})",
    r"(?:https?://)?(?:www\.)?youtube\.com/embed/([\w-]{11})",
]


def extract_video_id(url: str) -> Optional[str]:
    """Extrahiert die 11-stellige YouTube Video-ID aus einer beliebigen URL."""
    if not url:
        return None
    for pattern in _URL_PATTERNS:
        m = re.search(pattern, url)
        if m:
            return m.group(1)
    if re.fullmatch(r"[\w-]{11}", url):
        return url
    return None


def get_video_metadata(video_id: str) -> dict[str, Any]:
    """Holt Metadaten via yt-dlp (kein Download).

    Liefert das volle Spektrum der von yt-dlp exponierten
    ``info_dict``-Felder, gefiltert auf das was für unsere Pipeline
    sinnvoll ist.  yt-dlp selbst ist auf GitHub: ``yt-dlp/yt-dlp``.
    """
    if not video_id or len(video_id) != 11:
        raise InvalidURLError(f"invalid video id: {video_id}")
    url = f"https://www.youtube.com/watch?v={video_id}"
    opts = {"quiet": True, "no_warnings": True, "skip_download": True}
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except yt_dlp.utils.DownloadError as e:
        raise VideoNotFoundError(f"video not found: {e}") from e
    except Exception as e:
        logger.error("metadata extraction failed: %s", e)
        raise

    description = info.get("description", "") or ""

    # ── Hilfs-Extraktionen ──────────────────────────────────────────
    def _list(d: dict | None) -> list[str]:
        """Sprach-Keys aus einem {lang: [{fmt...}]}-Dict."""
        return list((d or {}).keys())

    def _captions(d: dict | None) -> list[dict[str, Any]]:
        """Formate pro Sprache: [{lang, formats: ['vtt','srt',...]}]."""
        out: list[dict[str, Any]] = []
        for lang, formats in (d or {}).items():
            fmt_names = [f.get("ext") for f in (formats or []) if f.get("ext")]
            out.append({
                "lang": lang,
                "is_auto": False,
                "formats": [n for n in fmt_names if n],
            })
        return out

    # ── Response ────────────────────────────────────────────────────
    return {
        "success": True,
        "video_id": video_id,
        "webpage_url": info.get("webpage_url") or url,

        # ── Identität ───────────────────────────────────────────────
        "title": info.get("title", ""),
        "channel": info.get("uploader") or info.get("channel", ""),
        "channel_id": info.get("channel_id") or info.get("uploader_id", ""),
        "channel_url": info.get("channel_url") or info.get("uploader_url"),
        "uploader": info.get("uploader", ""),
        "uploader_id": info.get("uploader_id", ""),
        "uploader_url": info.get("uploader_url", ""),
        "creators": info.get("creators") or [],
        "artist": info.get("artist"),

        # ── Beschreibung / Kategorien / Tags ─────────────────────────
        "description": description,
        "description_length": len(description),
        "tags": info.get("tags") or [],
        "categories": info.get("categories") or [],
        "license": info.get("license"),

        # ── Datum / Dauer ───────────────────────────────────────────
        "upload_date": info.get("upload_date", ""),
        "release_date": info.get("release_date"),
        "release_timestamp": info.get("release_timestamp"),
        "timestamp": info.get("timestamp"),
        "duration_sec": info.get("duration") or 0,
        "duration_string": info.get("duration_string"),

        # ── Statistik ────────────────────────────────────────────────
        "view_count": info.get("view_count") or 0,
        "like_count": info.get("like_count") or 0,
        "dislike_count": info.get("dislike_count") or 0,
        "repost_count": info.get("repost_count") or 0,
        "comment_count": info.get("comment_count") or 0,
        "channel_follower_count": info.get("channel_follower_count"),

        # ── Sprache / Verfügbarkeit ─────────────────────────────────
        "language": info.get("language", ""),
        "availability": info.get("availability"),     # public / unlisted / private / …
        "live_status": info.get("live_status"),       # not_live / is_live / was_live / is_upcoming
        "was_live": bool(info.get("was_live") or False),
        "playable_in_embed": bool(info.get("playable_in_embed") or False),
        "age_limit": info.get("age_limit") or 0,
        "is_live_content": bool(info.get("is_live_content") or False),

        # ── Thumbnails: volles Array (verschiedene Auflösungen) ────
        "thumbnail": info.get("thumbnail", ""),
        "thumbnails": info.get("thumbnails") or [],

        # ── Kapitel ─────────────────────────────────────────────────
        "chapters": info.get("chapters") or [],

        # ── Untertitel: pro Sprache mit Formaten ────────────────────
        "subtitles": _captions(info.get("subtitles")),
        "automatic_captions": _captions(info.get("automatic_captions")),
        "subtitle_languages": _list(info.get("subtitles")),
        "auto_caption_languages": _list(info.get("automatic_captions")),

        # ── Engagement ──────────────────────────────────────────────
        "heatmap": info.get("heatmap"),

        # ── Rohdaten für Diagnose ───────────────────────────────────
        "_raw_keys": sorted(info.keys()),
    }


def get_video_comments(video_id: str, max_comments: int = 500) -> dict[str, Any]:
    """Holt Top-Kommentare via yt-dlp."""
    if not video_id or len(video_id) != 11:
        raise InvalidURLError(f"invalid video id: {video_id}")
    url = f"https://www.youtube.com/watch?v={video_id}"
    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "getcomments": True,
        "extractor_args": {"youtube": {"max_comments": [str(max_comments)], "comment_sort": ["top"]}},
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except yt_dlp.utils.DownloadError as e:
        err = str(e).lower()
        if "comments" in err or "disabled" in err:
            raise CommentsUnavailableError(f"comments disabled: {e}") from e
        raise VideoNotFoundError(f"video not found: {e}") from e
    except Exception as e:
        logger.error("comments extraction failed: %s", e)
        raise CommentsUnavailableError(f"comments failed: {e}") from e

    raw = info.get("comments") or []
    comments: list[dict[str, Any]] = []
    for c in raw[:max_comments]:
        comments.append({
            "id": c.get("id", ""),
            "author": c.get("author", ""),
            "author_id": c.get("author_id", ""),
            "text": c.get("text", ""),
            "like_count": c.get("like_count") or 0,
            "reply_count": c.get("reply_count") or 0,
            "timestamp": c.get("timestamp"),
            "is_favorited": c.get("is_favorited", False),
            "is_pinned": c.get("is_pinned", False),
        })
    return {
        "success": True,
        "video_id": video_id,
        "count": len(comments),
        "truncated": len(raw) > max_comments,
        "comments": comments,
    }
