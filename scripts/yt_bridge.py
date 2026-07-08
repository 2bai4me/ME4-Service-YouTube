"""ME4-YouTube-Bridge — adaptiert ME4-YouTube-Response in SM-Producer-Format.

Hört auf Port 3002 und bietet exakt die gleichen Endpunkte wie der
SM-Producer /api/channels/transcript, nutzt intern aber den
ME4-YouTube Service (mit yt-dlp, load-balancer, parallelen Workern).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time
from typing import Any, Optional

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Projekt-Root zu sys.path, damit app.* importiert werden kann
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Einfaches Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)-20s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("me4-yt-bridge")

# Bridge-Settings
BRIDGE_PORT = int(os.environ.get("BRIDGE_PORT", "3002"))
ME4_YOUTUBE_URL = os.environ.get("ME4_YOUTUBE_URL", "http://127.0.0.1:8770")
ME4_YOUTUBE_API_KEY = os.environ.get("ME4_YOUTUBE_API_KEY", "ob-youtube-key-2026")

app = FastAPI(title="ME4-YouTube-Bridge", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class TranscriptRequest(BaseModel):
    url: str


def _format_upload_date(raw: str) -> str:
    """YYYYMMDD -> YYYY-MM-DD"""
    if not raw or len(raw) != 8:
        return raw or ""
    return f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}"


def _map_me4_to_smproducer(data: dict[str, Any], url: str, video_id: str) -> dict[str, Any]:
    """Mappt ME4-YouTube-Response in das SM-Producer-Format."""
    md = data.get("metadata") or {}
    tr = data.get("transcript") or {}
    comments_raw = data.get("comments") or []
    chapters_raw = md.get("chapters") or []
    snippets = tr.get("snippets") or []

    transcript_text = "\n".join(
        f"[{int(s.get('start', 0))}s] {s.get('text', '')}" for s in snippets
    )
    transcript_segments = [
        {
            "text": s.get("text", ""),
            "start": s.get("start", 0),
            "duration": s.get("duration", 0),
            "offset": s.get("start", 0),
        }
        for s in snippets
    ]
    comments = [
        {
            "author": c.get("author", ""),
            "text": c.get("text", ""),
            "likes": c.get("like_count", 0),
            "published": (
                time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(c["timestamp"]))
                if c.get("timestamp") else ""
            ),
        }
        for c in comments_raw[:20]
    ]
    chapters = [
        {"title": c.get("title", ""), "timestamp": c.get("start_time", 0)}
        for c in chapters_raw
    ]
    thumbnail = md.get("thumbnail", "")
    return {
        "title": md.get("title", ""),
        "description": md.get("description", ""),
        "duration": md.get("duration_sec", 0),
        "views": md.get("view_count", 0),
        "likes": md.get("like_count", 0),
        "uploadDate": _format_upload_date(md.get("upload_date", "")),
        "category": (md.get("categories") or [""])[0],
        "tags": md.get("tags") or [],
        "thumbnail": thumbnail,
        "thumbnails": [{"url": thumbnail, "width": 1280, "height": 720}] if thumbnail else [],
        "channelName": md.get("channel", ""),
        "channelId": md.get("channel_id", ""),
        "subscriberCount": "",
        "transcript": transcript_text,
        "transcriptSegments": transcript_segments,
        "comments": comments,
        "chapters": chapters,
        "videoId": video_id,
        "url": url,
        "_source": "me4-youtube",
    }


@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "service": "me4-youtube-bridge",
        "version": "1.0.0",
        "upstream": ME4_YOUTUBE_URL,
    }


@app.get("/api/manifest")
async def manifest():
    return {
        "service_id": "me4-youtube-bridge",
        "description": "Bridge zwischen SM-Producer und ME4-YouTube",
        "upstream": ME4_YOUTUBE_URL,
    }


@app.post("/api/channels/transcript")
async def transcript(req: TranscriptRequest):
    """SM-Producer-kompatibler Endpunkt: {url} -> YouTube-Daten."""
    import re
    m = re.search(r"(?:v=|\/)([a-zA-Z0-9_-]{11})", req.url)
    if not m:
        raise HTTPException(status_code=400, detail="Keine gueltige YouTube-URL")
    video_id = m.group(1)

    logger.info(f"Bridge: leite Transcript-Call fuer {video_id} an {ME4_YOUTUBE_URL}")
    try:
        async with httpx.AsyncClient(timeout=120) as c:
            r = await c.post(
                f"{ME4_YOUTUBE_URL}/api/process",
                json={
                    "url": req.url,
                    "download": False,
                    "include_description": True,
                    "include_transcript": True,
                    "include_comments": True,
                    "language": "de",
                    "max_comments": 20,
                },
                headers={"X-API-Key": ME4_YOUTUBE_API_KEY},
            )
            r.raise_for_status()
            data = r.json()
    except Exception as e:
        logger.error(f"Bridge: ME4-YouTube-Fehler: {e}")
        raise HTTPException(status_code=502, detail=f"ME4-YouTube: {e}")

    if data.get("status") != "ok":
        raise HTTPException(status_code=400, detail=data.get("error", "unknown"))

    return _map_me4_to_smproducer(data, req.url, video_id)


# === SCHRITT 2: Themen-Analyse =====================================

_STOPWORDS_DE = {
    "der", "die", "das", "ein", "eine", "und", "oder", "aber", "wenn", "weil",
    "ist", "sind", "war", "hat", "haben", "wird", "werden", "kann", "koennen",
    "nicht", "kein", "keine", "auch", "noch", "schon", "sehr", "ganz", "viel",
    "mehr", "weniger", "alle", "dieser", "diese", "dieses", "jener", "jene",
    "einem", "einer", "eines", "sich", "sie", "ihr", "ihm", "ihn", "wir", "uns",
    "du", "dich", "dir", "mich", "mir", "mein", "dein", "sein", "ihr", "unser",
    "euer", "was", "wer", "wie", "wo", "wann", "warum", "wieso", "weshalb",
    "dass", "weil", "damit", "sodass", "wenn", "falls", "ob", "als", "nach",
    "von", "vor", "mit", "bei", "aus", "zum", "zur", "ins", "im", "am", "an",
    "auf", "ueber", "unter", "durch", "gegen", "ohne", "um", "fuer", "bis",
    "seit", "waehrend", "trotz", "wegen", "statt", "anstatt", "ausserdem",
    "ja", "nein", "doch", "nur", "schon", "etwa", "circa", "ca", "ungefaehr",
    "gerade", "eben", "heute", "morgen", "gestern", "immer", "nie", "oft",
    "manchmal", "selten", "hier", "dort", "da", "wohin", "woher", "dann",
    "jetzt", "gleich", "bald", "endlich", "schliesslich", "zunaechst", "erst",
}


def _extract_keywords(text: str, top_n: int = 15, min_len: int = 4) -> list[tuple[str, int]]:
    """Extrahiert die haeufigsten Woerter (lowercase, ohne Stopwords)."""
    import re as _re
    words = _re.findall(r"[A-Za-zäöüÄÖÜß]{%d,}" % min_len, text.lower())
    freq: dict[str, int] = {}
    for w in words:
        if w in _STOPWORDS_DE:
            continue
        freq[w] = freq.get(w, 0) + 1
    return sorted(freq.items(), key=lambda x: -x[1])[:top_n]


def _smart_blocks(transcript: str, description: str, tags: list, comments: list, block_size: int = 3000) -> list[str]:
    """Erzeugt Analyse-Bloecke: erst Tags/Description (kurz), dann Transcript (lang)."""
    blocks = []
    # Block 1: Tags + Description-Header
    header = "YouTube-Tags: " + ", ".join(tags[:20]) + "\n\nVideo-Beschreibung (Auszug):\n" + description[:500]
    blocks.append(header)
    # Bloecke 2..N: Transcript-Teile
    remaining = transcript or ""
    while remaining:
        chunk = remaining[:block_size]
        # Versuche an Satzgrenze zu schneiden
        if len(remaining) > block_size:
            cut = chunk.rfind(". ")
            if cut > block_size // 2:
                chunk = chunk[: cut + 2]
        blocks.append("Transkript-Auszug:\n" + chunk)
        remaining = remaining[len(chunk):]
    return blocks


def _local_topic_suggestions(
    transcript_text: str, tags: list, comments: list, top_n: int = 8
) -> list[dict]:
    """Lokale Topic-Vorschlaege OHNE LLM (schnell, kostenlos).

    Basiert auf:
    - YouTube-Tags (direkt vom Video)
    - Haeufigste Woerter im Transkript
    - Top-Kommentare (was diskutieren die Zuschauer?)
    """
    suggestions: list[dict] = []
    seen_titles: set[str] = set()

    # 1) YouTube-Tags als direkte Topic-Vorschlaege
    for t in tags[:5]:
        title = t.strip()
        if title and title.lower() not in seen_titles and len(title) >= 3:
            suggestions.append({
                "title": title[:80],
                "description": f"Thema basierend auf YouTube-Tag des Videos.",
                "tags": title,
                "source": "youtube-tag",
                "confidence": 0.9,
            })
            seen_titles.add(title.lower())

    # 2) Haeufigste Transkript-Woerter als Topic-Vorschlaege
    keywords = _extract_keywords(transcript_text, top_n=10)
    for word, count in keywords[:5]:
        if word.lower() not in seen_titles and count >= 3:
            suggestions.append({
                "title": word.capitalize(),
                "description": f"Begriff kommt {count}x im Transkript vor.",
                "tags": word,
                "source": "transcript-freq",
                "confidence": min(0.5 + count / 20, 0.95),
            })
            seen_titles.add(word.lower())

    # 3) Top-Kommentare als Themen-Indikatoren (was bewegt die Zuschauer?)
    for c in sorted(comments, key=lambda x: x.get("likes", 0), reverse=True)[:3]:
        text = c.get("text", "").strip()
        if text and len(text) >= 15:
            # Erste 80 Zeichen als Titel-Vorschlag
            title = text[:80].split(". ")[0] + ("." if "." in text[:80] else "")
            if title.lower() not in seen_titles:
                suggestions.append({
                    "title": title[:80],
                    "description": f"Top-Kommentar mit {c.get('likes', 0)} Likes: \"{text[:120]}...\"",
                    "tags": "Community, Diskussion",
                    "source": "top-comment",
                    "confidence": 0.7,
                })
                seen_titles.add(title.lower())

    return suggestions[:top_n]


class AnalyzeRequest(BaseModel):
    url: str
    max_topics: int = 8


@app.post("/api/channels/analyze")
async def analyze_topics(req: AnalyzeRequest):
    """SCHRITT 2: Lokale Themen-Analyse aus YouTube-Daten.

    Liefert:
    - strukturierte Analyse-Bloecke (fuer LLM-Analyse)
    - lokale Topic-Vorschlaege (ohne LLM-Kosten)
    - Empfehlung welcher Block der wichtigste ist
    """
    import re
    m = re.search(r"(?:v=|\/)([a-zA-Z0-9_-]{11})", req.url)
    if not m:
        raise HTTPException(status_code=400, detail="Keine gueltige YouTube-URL")
    video_id = m.group(1)
    logger.info(f"Analyze-Call fuer {video_id}")

    # 1) YouTube-Daten holen (Transcript + Description + Comments)
    try:
        async with httpx.AsyncClient(timeout=120) as c:
            r = await c.post(
                f"{ME4_YOUTUBE_URL}/api/process",
                json={
                    "url": req.url,
                    "download": False,
                    "include_description": True,
                    "include_transcript": True,
                    "include_comments": True,
                    "language": "de",
                    "max_comments": 20,
                },
                headers={"X-API-Key": ME4_YOUTUBE_API_KEY},
            )
            r.raise_for_status()
            data = r.json()
    except Exception as e:
        logger.error(f"Analyze: ME4-YouTube-Fehler: {e}")
        raise HTTPException(status_code=502, detail=f"ME4-YouTube: {e}")

    if data.get("status") != "ok":
        raise HTTPException(status_code=400, detail=data.get("error", "unknown"))

    # 2) Daten extrahieren
    md = data.get("metadata") or {}
    tr = data.get("transcript") or {}
    snippets = tr.get("snippets") or []
    transcript_text = " ".join(s.get("text", "") for s in snippets)
    description = md.get("description", "")
    tags = md.get("tags") or []
    comments = data.get("comments") or []

    # 3) Smarte Analyse-Bloecke (fuer LLM)
    blocks = _smart_blocks(transcript_text, description, tags, comments)

    # 4) Lokale Topic-Vorschlaege (ohne LLM)
    local_topics = _local_topic_suggestions(transcript_text, tags, comments, top_n=req.max_topics)

    # 5) Statistiken
    keywords_top = _extract_keywords(transcript_text, top_n=10)

    return {
        "video_id": video_id,
        "url": req.url,
        "title": md.get("title", ""),
        "channel": md.get("channel", ""),
        "blocks": blocks,
        "block_count": len(blocks),
        "block_strategy": "header+transcript_chunks",
        "local_topics": local_topics,
        "local_topic_count": len(local_topics),
        "stats": {
            "transcript_length": len(transcript_text),
            "transcript_words": len(transcript_text.split()),
            "description_length": len(description),
            "tag_count": len(tags),
            "comment_count": len(comments),
            "top_keywords": [{"word": w, "count": c} for w, c in keywords_top],
        },
        "next_steps": [
            "1. Lokale Topic-Vorschlaege direkt nutzen (kostenlos)",
            "2. Oder: Bloecke an LLM (/api/chat) schicken fuer tiefere Analyse",
            "3. Ergebnis: /api/projects/.../thema/analyse-block",
        ],
        "_source": "me4-youtube-bridge",
        "_step": "2-analyze",
    }


if __name__ == "__main__":
    import uvicorn
    print(f"ME4-YouTube-Bridge startet auf Port {BRIDGE_PORT}")
    print(f"Upstream: {ME4_YOUTUBE_URL}")
    uvicorn.run(app, host="0.0.0.0", port=BRIDGE_PORT, log_level="warning")
