"""
Persistence-Modul fuer ME4-YouTube Ergebnisse.
- SQLite-DB fuer strukturierte Daten (URL, Title, Status, Timestamp, JSON-Path)
- JSON-Dateien im data/-Verzeichnis fuer volle Responses
"""
from __future__ import annotations

import json
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

# Daten-Verzeichnis: data/ relativ zum aktuellen Arbeitsverzeichnis
DATA_DIR = Path("data").resolve()
DATA_DIR.mkdir(parents=True, exist_ok=True)

# SQLite-DB
DB_PATH = DATA_DIR / "youtube_results.db"

# Schema
SCHEMA = """
CREATE TABLE IF NOT EXISTS results (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id          TEXT UNIQUE NOT NULL,
    url             TEXT NOT NULL,
    video_id        TEXT,
    title           TEXT,
    channel         TEXT,
    duration_sec    REAL,
    view_count      INTEGER,
    like_count      INTEGER,
    status          TEXT NOT NULL DEFAULT 'completed',
    worker_id       TEXT,
    duration_proc   REAL,
    json_path       TEXT,
    transcript_segments INTEGER DEFAULT 0,
    comments_count  INTEGER DEFAULT 0,
    thumbnail       TEXT,
    language        TEXT,
    chapters_count  INTEGER DEFAULT 0,
    has_download    INTEGER DEFAULT 0,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_results_url ON results(url);
CREATE INDEX IF NOT EXISTS idx_results_video_id ON results(video_id);
CREATE INDEX IF NOT EXISTS idx_results_created_at ON results(created_at);
CREATE INDEX IF NOT EXISTS idx_results_status ON results(status);
"""

def _conn() -> sqlite3.Connection:
    """Gibt eine neue DB-Connection zurueck (thread-safe, jedes Mal neue)."""
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def init_db() -> None:
    """Initialisiert die DB mit dem Schema."""
    with _conn() as conn:
        conn.executescript(SCHEMA)
        conn.commit()
    print(f"[persistence] DB initialisiert: {DB_PATH}")

def save_result(job_id: str, url: str, response: dict[str, Any]) -> dict[str, Any]:
    """Speichert ein Process-Ergebnis sowohl als JSON als auch in SQLite.

    Args:
        job_id: Eindeutige ID (z.B. timestamp-basiert)
        url: YouTube-URL
        response: Die vollstaendige Response von /api/process

    Returns:
        Dict mit gespeicherten Metadaten (id, json_path, db_path)
    """
    # 1) JSON-Datei speichern (vollstaendige Response)
    json_path = DATA_DIR / f"{job_id}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(response, f, ensure_ascii=False, indent=2, default=str)

    # 2) Felder extrahieren (Worker packt Daten in 'metadata'-Sub-Objekt)
    metadata = response.get("metadata") or {}
    transcript = response.get("transcript") or {}
    comments = response.get("comments") or []
    chapters = metadata.get("chapters") or response.get("chapters") or []
    download_path = response.get("download_path")

    video_id = response.get("video_id") or metadata.get("video_id")
    title = (metadata.get("title") or "")[:500]
    channel = (metadata.get("channel") or "")[:200]
    duration_sec = metadata.get("duration_sec")
    view_count = metadata.get("view_count", 0)
    like_count = metadata.get("like_count", 0)
    worker_id = response.get("worker_id", "")
    duration_proc = response.get("duration_sec", 0)
    # Worker liefert "snippets" (nicht "segments")
    transcript_segs = transcript.get("snippet_count") or len(transcript.get("snippets", []) or transcript.get("segments", []))
    comments_count = len(comments)
    chapters_count = len(chapters)
    has_download = 1 if download_path else 0
    status = "completed" if response.get("error") is None else "error"
    thumbnail = metadata.get("thumbnail", "")[:500]
    language = metadata.get("language", "")[:20]

    # 3) In SQLite speichern
    init_db()
    with _conn() as conn:
        cursor = conn.execute("""
            INSERT OR REPLACE INTO results (
                job_id, url, video_id, title, channel,
                duration_sec, view_count, like_count, status,
                worker_id, duration_proc, json_path,
                transcript_segments, comments_count,
                thumbnail, language, chapters_count, has_download,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
        """, (
            job_id, url, video_id, title, channel,
            duration_sec, view_count, like_count, status,
            worker_id, duration_proc, str(json_path.relative_to(DATA_DIR.parent)),
            transcript_segs, comments_count,
            thumbnail, language, chapters_count, has_download
        ))
        conn.commit()
        result_id = cursor.lastrowid

    return {
        "id": result_id,
        "job_id": job_id,
        "json_path": str(json_path),
        "db_path": str(DB_PATH),
        "status": status,
        "title": title,
        "channel": channel,
        "duration_sec": duration_sec,
        "transcript_segments": transcript_segs,
        "comments_count": comments_count,
    }

def list_results(limit: int = 20) -> list[dict[str, Any]]:
    """Listet die letzten Ergebnisse."""
    init_db()
    with _conn() as conn:
        rows = conn.execute("""
            SELECT id, job_id, url, video_id, title, channel,
                   duration_sec, view_count, status, worker_id,
                   duration_proc, transcript_segments, comments_count,
                   thumbnail, language, chapters_count, has_download,
                   json_path, created_at
            FROM results
            ORDER BY created_at DESC
            LIMIT ?
        """, (limit,)).fetchall()
    return [dict(r) for r in rows]

def get_result(job_id: str) -> Optional[dict[str, Any]]:
    """Holt ein einzelnes Ergebnis."""
    init_db()
    with _conn() as conn:
        row = conn.execute("SELECT * FROM results WHERE job_id = ?", (job_id,)).fetchone()
    return dict(row) if row else None

def get_stats() -> dict[str, Any]:
    """Liefert Statistiken."""
    init_db()
    with _conn() as conn:
        total = conn.execute("SELECT COUNT(*) as c FROM results").fetchone()["c"]
        completed = conn.execute("SELECT COUNT(*) as c FROM results WHERE status='completed'").fetchone()["c"]
        error = conn.execute("SELECT COUNT(*) as c FROM results WHERE status='error'").fetchone()["c"]
        total_segments = conn.execute("SELECT COALESCE(SUM(transcript_segments),0) as c FROM results").fetchone()["c"]
        total_comments = conn.execute("SELECT COALESCE(SUM(comments_count),0) as c FROM results").fetchone()["c"]
    return {
        "total_results": total,
        "completed": completed,
        "errors": error,
        "total_transcript_segments": total_segments,
        "total_comments": total_comments,
        "data_dir": str(DATA_DIR),
        "db_path": str(DB_PATH),
    }
