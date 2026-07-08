"""YouTube Transkript via youtube-transcript-api."""
from __future__ import annotations

from typing import Any, Optional

from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import (
    NoTranscriptFound,
    TranscriptsDisabled,
    VideoUnavailable,
)

from app.exceptions import (
    InvalidURLError,
    TranscriptUnavailableError,
    VideoNotFoundError,
)
from app.extractor import extract_video_id
from app.logging_config import get_logger

logger = get_logger(__name__)


def get_transcript(
    video_id: str,
    languages: Optional[list[str]] = None,
    translate_to: Optional[str] = None,
) -> dict[str, Any]:
    """Holt Transkript und optional Übersetzung."""
    if not video_id or len(video_id) != 11:
        raise InvalidURLError(f"invalid video id: {video_id}")
    languages = languages or ["de", "en"]

    try:
        api = YouTubeTranscriptApi()
        transcript = None
        # Erst in gewünschten Sprachen suchen
        try:
            transcript = api.fetch(video_id, languages=languages)
        except NoTranscriptFound:
            # Fallback: irgendein verfügbarer Transkript, dann ggf. übersetzen
            tlist = api.list(video_id)
            available = [t.language_code for t in tlist]
            logger.info("requested langs %s not available, found: %s", languages, available)
            if not available:
                raise TranscriptUnavailableError("no transcripts available")
            transcript = api.fetch(video_id, languages=[available[0]])

        if translate_to and transcript.language_code != translate_to:
            try:
                # Versuche, Übersetzung in Zielsprache zu finden
                tlist = api.list(video_id)
                for t in tlist:
                    if t.language_code == transcript.language_code and t.is_translatable:
                        transcript = t.translate(translate_to).fetch()
                        break
            except Exception as e:  # noqa: BLE001
                logger.warning("translation to %s failed: %s", translate_to, e)

        # Snippets serialisieren
        snippets = [
            {
                "text": s.text,
                "start": s.start,
                "duration": s.duration,
            }
            for s in transcript.snippets
        ]
        return {
            "success": True,
            "video_id": video_id,
            "language": transcript.language_code,
            "is_generated": transcript.is_generated or False,
            "is_translated": getattr(transcript, "translation_language", None) is not None,
            "snippet_count": len(snippets),
            "snippets": snippets,
        }
    except (TranscriptsDisabled, NoTranscriptFound) as e:
        raise TranscriptUnavailableError(f"transcript unavailable: {e}") from e
    except VideoUnavailable as e:
        raise VideoNotFoundError(f"video unavailable: {e}") from e
    except Exception as e:
        logger.exception("transcript extraction failed")
        raise TranscriptUnavailableError(f"transcript failed: {e}") from e


def transcript_to_plain_text(transcript_data: dict[str, Any]) -> str:
    """Wandelt Snippets in reinen Text um."""
    snippets = transcript_data.get("snippets") or []
    return " ".join(s.get("text", "") for s in snippets).strip()
