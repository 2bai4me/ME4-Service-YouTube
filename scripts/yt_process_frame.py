"""ME4-YouTube Process-Frame — Server-seitig gerenderter Loading-Dialog.

Wird vom SM-Producer-Frontend in einem iframe geladen.
Zeigt Live-Status der YouTube-Verarbeitung (Server-driven).
Sendet Ergebnis am Ende via postMessage an den Parent (SM-Producer).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sys
import time
from typing import Any, Optional

# Projekt-Root zu sys.path, damit app.* importiert werden kann
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
import httpx

from app.config import settings as me4_settings
from app.logging_config import get_logger, setup_logging

setup_logging()
logger = get_logger("me4-yt-process-frame")

# Settings
FRAME_PORT = int(os.environ.get("FRAME_PORT", "3003"))
ME4_YOUTUBE_URL = os.environ.get("ME4_YOUTUBE_URL", "http://127.0.0.1:8770")
ME4_YOUTUBE_API_KEY = os.environ.get("ME4_YOUTUBE_API_KEY", "ob-youtube-key-2026")

app = FastAPI(title="ME4-YouTube-ProcessFrame", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


PROCESS_HTML = """<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>ME4-YouTube Process-Frame</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, system-ui, sans-serif;
    background: #0a0e1a;
    color: #e2e8f0;
    padding: 16px;
    height: 100vh;
    overflow: hidden;
    display: flex; flex-direction: column;
  }
  .header {
    display: flex; align-items: center; gap: 12px;
    padding-bottom: 12px; border-bottom: 1px solid #1e293b;
    margin-bottom: 12px;
  }
  .header h1 { font-size: 1.1rem; font-weight: 700; color: #38bdf8; }
  .header .status { margin-left: auto; font-size: 0.85rem; color: #94a3b8; }
  .header .status.connected { color: #22c55e; }
  .header .status.error { color: #ef4444; }
  .progress-bar {
    height: 6px; background: #1e293b; border-radius: 3px; overflow: hidden;
    margin-bottom: 12px;
  }
  .progress-bar .fill {
    height: 100%; background: linear-gradient(90deg, #0ea5e9, #38bdf8);
    width: 0%; transition: width 0.4s ease;
  }
  .log-container {
    flex: 1; overflow-y: auto; background: #050811;
    border: 1px solid #1e293b; border-radius: 8px;
    padding: 12px; font-family: 'Menlo', monospace; font-size: 0.78rem;
  }
  .log-entry {
    margin-bottom: 4px; padding: 2px 0;
    color: #94a3b8; display: flex; align-items: flex-start; gap: 8px;
  }
  .log-entry .ts { color: #38bdf8; min-width: 64px; }
  .log-entry.success { color: #22c55e; font-weight: 600; }
  .log-entry.error { color: #ef4444; font-weight: 600; }
  .log-entry.warn { color: #f97316; }
  .log-entry.info { color: #38bdf8; }
  .footer {
    display: flex; gap: 8px; padding-top: 12px;
    border-top: 1px solid #1e293b; margin-top: 12px;
  }
  .btn {
    padding: 8px 16px; border: none; border-radius: 6px;
    font-size: 0.85rem; font-weight: 600; cursor: pointer;
  }
  .btn-primary { background: #0ea5e9; color: white; }
  .btn-primary:hover { background: #38bdf8; }
  .btn-primary:disabled { background: #1e293b; color: #64748b; cursor: not-allowed; }
  .btn-secondary { background: #1e293b; color: #e2e8f0; }
  .btn-success { background: #22c55e; color: white; }
  .status-pill {
    display: inline-flex; align-items: center; gap: 6px;
    padding: 4px 10px; border-radius: 12px;
    font-size: 0.75rem; font-weight: 600;
  }
  .status-pill.idle { background: rgba(148, 163, 184, 0.15); color: #94a3b8; }
  .status-pill.running { background: rgba(56, 189, 248, 0.15); color: #38bdf8; }
  .status-pill.success { background: rgba(34, 197, 94, 0.15); color: #22c55e; }
  .status-pill.error { background: rgba(239, 68, 68, 0.15); color: #ef4444; }
  .data-preview {
    background: #0f172a; border: 1px solid #1e293b; border-radius: 6px;
    padding: 8px; margin-top: 8px; font-size: 0.75rem;
    max-height: 200px; overflow-y: auto; color: #94a3b8;
  }
  .data-preview strong { color: #38bdf8; }
</style>
</head>
<body>
  <div class="header">
    <span style="font-size:1.5rem">▶</span>
    <h1>ME4-YouTube Process-Frame</h1>
    <span id="status-pill" class="status-pill idle">● idle</span>
    <span class="status">v1.0.0</span>
  </div>

  <div class="progress-bar"><div class="fill" id="progress-fill"></div></div>

  <div class="log-container" id="log"></div>

  <div class="footer">
    <button class="btn btn-primary" id="btn-close" disabled>Schliessen & Daten uebernehmen</button>
    <button class="btn btn-secondary" id="btn-cancel">Abbrechen</button>
  </div>

  <div id="data-preview" class="data-preview" style="display:none"></div>

<script>
const URL_PARAM = new URLSearchParams(window.location.search).get('url');
const log = document.getElementById('log');
const progressFill = document.getElementById('progress-fill');
const statusPill = document.getElementById('status-pill');
const btnClose = document.getElementById('btn-close');
const btnCancel = document.getElementById('btn-cancel');
const dataPreview = document.getElementById('data-preview');

let result = null;
let error = null;

function addLog(msg, type='') {
  const ts = new Date().toLocaleTimeString('de-DE');
  const div = document.createElement('div');
  div.className = 'log-entry ' + type;
  div.innerHTML = '<span class="ts">' + ts + '</span><span>' + msg + '</span>';
  log.appendChild(div);
  log.scrollTop = log.scrollHeight;
}

function setStatus(text, cls) {
  statusPill.className = 'status-pill ' + cls;
  statusPill.textContent = '● ' + text;
}

function setProgress(pct) {
  progressFill.style.width = pct + '%';
}

function sendToParent(data) {
  if (window.parent && window.parent !== window) {
    window.parent.postMessage({
      type: 'me4-youtube-result',
      data: data,
      error: error
    }, '*');
  }
}

function showDataPreview(d) {
  if (!d) return;
  dataPreview.style.display = 'block';
  dataPreview.innerHTML = '<strong>Bereit zur Uebernahme:</strong> ' +
    '<br>title: ' + (d.title || '?').substring(0, 60) +
    '<br>channel: ' + (d.channelName || '?') +
    '<br>transcript: ' + ((d.transcript || '').length) + ' Zeichen' +
    '<br>description: ' + ((d.description || '').length) + ' Zeichen';
}

async function processYouTube() {
  if (!URL_PARAM) {
    addLog('FEHLER: Keine URL im Query-Parameter', 'error');
    setStatus('error', 'error');
    return;
  }
  addLog('URL: ' + URL_PARAM, 'info');
  setStatus('connecting', 'running');
  setProgress(20);

  try {
    addLog('-> ME4-YouTube Service: lade Transkript + Beschreibung...', 'info');
    const t0Resp = await fetch('/api/proxy/transcript', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({url: URL_PARAM})
    });
    setProgress(70);
    if (!t0Resp.ok) {
      const e = await t0Resp.json().catch(() => ({}));
      throw new Error(e.error || t0Resp.statusText);
    }
    const data = await t0Resp.json();
    addLog('Transkript geladen (' + (data.transcript || '').length + ' Zeichen)', 'success');
    if (data.description) {
      addLog('Beschreibung geladen (' + (data.description || '').length + ' Zeichen)', 'success');
    } else {
      addLog('Keine Beschreibung verfuegbar', 'warn');
    }

    // Filter: nur das, was SM-Producer braucht
    const minimal = {
      url: data.url,
      videoId: data.videoId,
      title: data.title,
      channelName: data.channelName,
      transcript: data.transcript || '',
      description: data.description || ''
    };

    setProgress(100);
    setStatus('done', 'success');
    addLog('FERTIG: Transkript + Beschreibung bereit fuer SM-Producer', 'success');
    result = minimal;
    showDataPreview(minimal);
    btnClose.disabled = false;
    btnClose.classList.remove('btn-primary');
    btnClose.classList.add('btn-success');

    // AUTOMATISCH schliessen nach kurzer Anzeige (800ms)
    addLog('Frame schliesst automatisch...', 'info');
    setTimeout(() => {
      if (result) sendToParent(result);
      window.close();
    }, 800);
  } catch(e) {
    addLog('FEHLER: ' + e.message, 'error');
    setStatus('error', 'error');
    error = e.message;
  }
}

btnClose.onclick = () => {
  if (result) sendToParent(result);
  window.close();
};

btnCancel.onclick = () => {
  sendToParent({cancelled: true, url: URL_PARAM});
  window.close();
};

window.addEventListener('load', () => {
  setStatus('running', 'running');
  processYouTube();
});
</script>
</body>
</html>
"""


def _format_upload_date(raw: str) -> str:
    if not raw or len(raw) != 8:
        return raw or ""
    return f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}"


def _map_me4_to_smproducer(data: dict[str, Any], url: str, video_id: str) -> dict[str, Any]:
    md = data.get("metadata") or {}
    tr = data.get("transcript") or {}
    comments_raw = data.get("comments") or []
    chapters_raw = md.get("chapters") or []
    snippets = tr.get("snippets") or []
    transcript_text = "\n".join(
        f"[{int(s.get('start', 0))}s] {s.get('text', '')}" for s in snippets
    )
    transcript_segments = [
        {"text": s.get("text", ""), "start": s.get("start", 0), "duration": s.get("duration", 0), "offset": s.get("start", 0)}
        for s in snippets
    ]
    comments = [
        {
            "author": c.get("author", ""),
            "text": c.get("text", ""),
            "likes": c.get("like_count", 0),
            "published": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(c["timestamp"])) if c.get("timestamp") else "",
        }
        for c in comments_raw[:20]
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
        "chapters": [{"title": c.get("title", ""), "timestamp": c.get("start_time", 0)} for c in chapters_raw],
        "videoId": video_id,
        "url": url,
        "_source": "me4-youtube",
    }


@app.get("/health")
async def health():
    return {"status": "ok", "service": "me4-yt-process-frame", "port": FRAME_PORT}


@app.get("/channels/youtube-process", response_class=HTMLResponse)
async def youtube_process(url: str = Query(...)):
    """Hauptseite: Wird im iframe vom SM-Producer geladen."""
    return PROCESS_HTML


@app.post("/api/proxy/transcript")
async def proxy_transcript(req: dict[str, Any]):
    """Proxy-Call: SM-Producer -> Bridge -> ME4-YouTube (Schritt 1)."""
    url = req.get("url", "")
    m = re.search(r"(?:v=|\/)([a-zA-Z0-9_-]{11})", url)
    if not m:
        raise HTTPException(status_code=400, detail="Keine gueltige YouTube-URL")
    video_id = m.group(1)
    try:
        async with httpx.AsyncClient(timeout=120) as c:
            r = await c.post(
                f"{ME4_YOUTUBE_URL}/api/process",
                json={
                    "url": url,
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
        raise HTTPException(status_code=502, detail=f"ME4-YouTube: {e}")
    if data.get("status") != "ok":
        raise HTTPException(status_code=400, detail=data.get("error", "unknown"))
    return _map_me4_to_smproducer(data, url, video_id)


@app.post("/api/proxy/analyze")
async def proxy_analyze(req: dict[str, Any]):
    """Proxy-Call: SM-Producer -> Bridge -> ME4-YouTube (Schritt 2)."""
    url = req.get("url", "")
    max_topics = int(req.get("max_topics", 8))
    m = re.search(r"(?:v=|\/)([a-zA-Z0-9_-]{11})", url)
    if not m:
        raise HTTPException(status_code=400, detail="Keine gueltige YouTube-URL")
    try:
        async with httpx.AsyncClient(timeout=120) as c:
            r = await c.post(
                f"{ME4_YOUTUBE_URL}/api/process",
                json={
                    "url": url,
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
        raise HTTPException(status_code=502, detail=f"ME4-YouTube: {e}")
    if data.get("status") != "ok":
        raise HTTPException(status_code=400, detail=data.get("error", "unknown"))
    # Lokale Topic-Detection
    md = data.get("metadata") or {}
    tr = data.get("transcript") or {}
    snippets = tr.get("snippets") or []
    transcript_text = " ".join(s.get("text", "") for s in snippets)
    tags = md.get("tags") or []
    comments = data.get("comments") or []
    # Tags als Topics
    local_topics = []
    for t in tags[:5]:
        if t and len(t) >= 3:
            local_topics.append({
                "title": t[:80],
                "description": "YouTube-Tag",
                "tags": t,
                "source": "youtube-tag",
                "confidence": 0.9,
            })
    return {
        "video_id": m.group(1),
        "url": url,
        "title": md.get("title", ""),
        "local_topics": local_topics,
        "local_topic_count": len(local_topics),
        "_source": "me4-youtube",
    }


if __name__ == "__main__":
    import uvicorn
    print(f"ME4-YouTube-ProcessFrame startet auf Port {FRAME_PORT}")
    print(f"Upstream ME4-YouTube: {ME4_YOUTUBE_URL}")
    uvicorn.run(app, host="0.0.0.0", port=FRAME_PORT, log_level="warning")
