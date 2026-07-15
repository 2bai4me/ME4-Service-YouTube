"""Session-basierte Persistenz für ME4-YouTube.

Jede Session (identifiziert durch eine vom Baustein vergebene ID) bekommt
ein eigenes Verzeichnis unter ``data/session/<session_id>/`` (singular —
matches spec AD-8 / Phase 4 ``/work/session/<sid>/`` and resolves the
ME4-UI response-validator Stage 3 "does not end with the canonical
/work/session/<sid>/results" warning).  Darin liegt eine ``Notes.md``
Logdatei und pro Funktionsaufruf eine Sequenz von drei Datei-Ansichten
desselben logischen Ergebnisses unter
``results/<sid>.<NN>result.{json,md,html}``.

Drei Dateiansichten (``json``/``md``/``html``) zaehlen als EINE Sequenz.
``Notes.md`` wird per Call angehaengt, nie ueberschrieben, und beginnt
auf Zeile 1 immer idempotent mit ``# Session <safe_sid>``.

Reads akzeptieren fuer mindestens eine Minor-Version beide Layouts
(singular + legacy plural) — siehe ``resolve_session_dir``.  Writes
gehen immer in das kanonische singular-Layout.

Migration vom alten ``data/sessions/<sid>/``-Layout wird vom
Service-Start (``main.py``) bzw. vom Standalone-Script
``scripts/migrate_session_layout.py`` ausgefuehrt.

Das Baustein zeigt im Chat nur noch den Pfad — die eigentlichen Daten
werden vom Service bei sich lokal abgelegt.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import re
from pathlib import Path
from typing import Any

import markdown as _md

from app.config import settings
from app.logging_config import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Pfad-Layout  (Spec AD-8 / Phase 4: singular ``session/``)
# ---------------------------------------------------------------------------
#
#   <data-root>/session/<safe_sid>/        # kanonisch (singular)
#     Notes.md                             # Logdatei, erste Zeile = Session-ID
#     results/                             # Resultset-Verzeichnis
#       <safe_sid>.01result.json
#       <safe_sid>.01result.md
#       <safe_sid>.01result.html
#       <safe_sid>.02result.json
#       <safe_sid>.02result.md
#       <safe_sid>.02result.html
#       <safe_sid>.NNresult.<ext>          # per-call Artefakt-Downloads
#
#   <data-root>/sessions/<safe_sid>/       # legacy (plural) — read-only
#                                          # nach v1.1.0-Migration
#
# Drei Dateiansichten (json/md/html) zaehlen als EINE Sequenz (F-05/YT-02);
# ``next_function_index`` zaehlt nur Sequenzen, deren <sid>-Segment zur
# aufrufenden session_id passt (Cross-Session-Schutz).
#

def _slug(s: str) -> str:
    """Sanitize a function name for use as a directory name."""
    return (
        s.lower()
        .replace(" ", "-")
        .replace("(", "")
        .replace(")", "")
        .replace("/", "-")
    )


def get_session_dir(session_id: str) -> Path:
    """Canonical root directory for a session: ``<DATA_DIR>/session/<safe_id>``.

    Singular ``session/`` (spec AD-8 / Phase 4) — resolves the
    ME4-UI response-validator Stage 3 "does not end with the canonical
    /work/session/<sid>/results" warning.

    The function ALWAYS returns the canonical (singular) path and
    creates it on demand; it NEVER touches the legacy ``sessions/``
    directory.  For backward-compatible reads (accept both layouts for
    at least one minor release), use :func:`resolve_session_dir` instead.

    Args:
        session_id: The raw session id (will be sanitised to ``safe_id``
            — only alnum + ``-`` + ``_`` are kept).

    Returns:
        Absolute path to ``<DATA_DIR>/session/<safe_id>/`` (created if
        missing).  Always uses forward-slashes in its string form on
        POSIX; on Windows, ``Path`` already uses the platform separator.
    """
    safe_id = "".join(c for c in session_id if c.isalnum() or c in "-_") or "unknown"
    base = Path(settings.data_dir) / "session" / safe_id
    base.mkdir(parents=True, exist_ok=True)
    return base


def resolve_session_dir(session_id: str) -> Path:
    """Backward-compat read-path: returns canonical or legacy session dir.

    Resolution order (creates canonical if NEITHER exists):

      1. If ``<DATA_DIR>/session/<safe_id>/`` exists, return it
         (canonical, post-migration state).
      2. Else if ``<DATA_DIR>/sessions/<safe_id>/`` exists, return it
         (legacy, pre-v1.1.0 state — reads still accepted for one minor
         release so the migration is non-disruptive).
      3. Else create and return the canonical path
         (``<DATA_DIR>/session/<safe_id>/``).

    This helper is intended for **read** code paths that must keep
    working during the singular transition.  Write code paths
    (``write_result`` etc.) MUST use :func:`get_session_dir` directly
    so new data always lands in the canonical singular layout.

    Args:
        session_id: The raw session id (sanitised internally).

    Returns:
        Absolute path to the resolved session directory.  Does NOT
        create directories in the legacy case (the data is already on
        disk); does create the canonical directory when neither layout
        exists yet.
    """
    safe_id = "".join(c for c in session_id if c.isalnum() or c in "-_") or "unknown"
    data_root = Path(settings.data_dir)
    canonical = data_root / "session" / safe_id
    if canonical.exists():
        return canonical
    legacy = data_root / "sessions" / safe_id
    if legacy.exists():
        return legacy
    # Neither exists — create canonical (NEVER touch legacy at write-time).
    canonical.mkdir(parents=True, exist_ok=True)
    return canonical


def get_function_dir(session_id: str, function_name: str) -> Path:
    """DEPRECATED -- Per-call subdirectory: <session>/<NN-slug>/.

    Wird seit Phase 2 (F-03 / F-04) NICHT mehr von ``write_result``
    benutzt.  Schreiber schreiben jetzt flach nach
    ``<session>/results/<sid>.<NN>result.{ext}``.  Diese Funktion bleibt
    fuer Alt-Aufrufer und Pre-Phase-2-Tests als Legacy-Stub erhalten
    (gibt weiterhin einen Per-Call-Subdir zurueck, ohne den aber nichts
    mehr geschrieben wird).

    Neue Code-Pfade sollten stattdessen ``get_results_dir`` +
    ``next_function_index`` verwenden.
    """
    base = get_session_dir(session_id)
    existing = sorted(p for p in base.iterdir() if p.is_dir() and p.name[:2].isdigit())
    next_idx = len(existing) + 1
    func_dir = base / f"{next_idx:02d}-{_slug(function_name)}"
    func_dir.mkdir(parents=True, exist_ok=True)
    return func_dir


# ---------------------------------------------------------------------------
# Sequenz-Parser (F-05, YT-02)
# ---------------------------------------------------------------------------
#
#   <session_root>/results/<sid>.<NN>result.{json,md,html}
#
# Drei Dateiansichten desselben logischen Ergebnisses (json, md, html)
# zählen als EINE Sequenz. Der nächste Funktionsaufruf erhält NN+1.
# Vorhandene Dateien dürfen nicht überschrieben werden.
#

# Anchor: <sid> (mindestens ein Nicht-Punkt-Zeichen, kein '.' im sid).
# Danach literal '.', genau zwei Ziffern, literal 'result.', dann eine
# der drei erlaubten Extensions (json|md|html) am Stringende.
# Beispiel-Match: "abc123.01result.json"  -> sid="abc123", nn="01", ext="json"
# Negativ-Beispiele (kein Match):
#   "Notes.md"                -> falsche Extension
#   ".DS_Store"               -> falsche Form
#   "abc.01resultJson"        -> falsche Extension (CamelCase)
#   "abc123.1result.json"     -> nur eine Ziffer
#   "abc.01.results.json"     -> extra '.' vor 'result'
_RESULT_RE = re.compile(
    r"^(?P<sid>[^.]+)\.(?P<nn>\d{2})result\.(?P<ext>json|md|html)$"
)


def get_results_dir(session_id: str) -> Path:
    """Directory for structured result files: ``<session_root>/results/``.

    Returns the canonical flat-resultset directory for the given session
    id and ensures it exists on disk.  This layout (F-05 / YT-02) places
    ``<sid>.<NN>result.{json,md,html}`` side-by-side inside ``results/``;
    three file-views of the same logical result count as ONE sequence.
    """
    d = get_session_dir(session_id) / "results"
    d.mkdir(parents=True, exist_ok=True)
    return d


def next_function_index(session_id: str) -> str:
    """Nächste freie 2-stellige Sequenz für Result-Dateien.

    Pattern: ``<sid>.<NN>result.{json,md,html}``. Drei Dateiansichten
    desselben logischen Ergebnisses zählen als EINE Sequenz. Der nächste
    Aufruf erhält NN+1.

    Verhalten:
      * Nur Dateien, die exakt auf das Regex-Pattern matchen, zählen.
      * ``Notes.md``, Verzeichnisse und alle anderen Dateien werden
        ignoriert.
      * Sequenzen anderer Sessions (anderer ``<sid>``-Prefix im selben
        Verzeichnis) werden ignoriert.
      * Rückgabe ist immer als 2-stellig formatierter String
        (``"01"`` ... ``"99"``), damit Aufrufer die Formatierung nicht
        doppelt anwenden müssen.

    Args:
        session_id: Die Session-ID, deren Result-Verzeichnis gescannt
            wird. Der ``<sid>``-Anteil im Filename muss mit dieser ID
            übereinstimmen, sonst wird die Datei nicht gezählt.

    Returns:
        Format-String ``"01"``, ``"02"``, ... ``"99"``.
    """
    results = get_results_dir(session_id)
    max_idx = 0
    for p in results.iterdir():
        if not p.is_file():
            continue
        m = _RESULT_RE.match(p.name)
        if not m:
            continue
        # Defensiv: der Regex [^.]+ würde auch fremde Sessions matchen,
        # wenn Dateien aus verschiedenen Sessions versehentlich im selben
        # results/-Verzeichnis landen. Wir zählen nur Sequenzen, deren
        # <sid>-Segment zur aufrufenden session_id passt.
        if m.group("sid") != session_id:
            continue
        idx = int(m.group("nn"))
        if idx > max_idx:
            max_idx = idx
    return f"{max_idx + 1:02d}"


def to_windows_url(path: Path | str) -> str:
    """Backward-compat shim for ``to_platform_path(path)`` (Phase 4b).

    Spec YT-03 + Top-Level-Response example.  This function predates the
    Phase-4b WSL->Windows translation setting; it now delegates to
    ``app.path_utils.to_platform_path`` so the same call site picks up
    ``settings.windows_path_translation`` automatically.  New code should
    call ``to_platform_path`` directly (the keyword-only ``windows``
    override is the canonical knob).
    """
    # Local import to avoid a circular dep with ``app.config`` during
    # interpreter bootstrap.
    from app.path_utils import to_platform_path
    return to_platform_path(path)


# ---------------------------------------------------------------------------
# Persistenz
# ---------------------------------------------------------------------------

def update_session_notes(
    session_id: str,
    function_name: str,
    result: dict[str, Any],
    request: dict[str, Any] | None = None,
) -> None:
    """Append one section to <session>/Notes.md and ensure the first
    line is the session id itself (idempotent).
    """
    base = get_session_dir(session_id)
    notes_path = base / "Notes.md"
    ts = _dt.datetime.now().isoformat(timespec="seconds")
    lines: list[str] = []

    if not notes_path.exists():
        # First write: the session id as the very first line.
        lines.append(f"# Session `{session_id}`\n")
        lines.append(f"_Erstellt: {ts}_\n")

    rel = f"`{function_name}`"
    lines.append(f"\n## {ts} — {rel}\n")
    if request:
        url = request.get("url")
        if url:
            lines.append(f"- **URL:** `{url}`")
        lang = request.get("language")
        if lang:
            lines.append(f"- **Sprache:** `{lang}`")
    ok = result.get("success")
    if ok is not None:
        lines.append(f"- **Result:** {'✅ success' if ok else '❌ failed'}")
    # link to the result files -- built from the canonical paths set by
    # write_result (Phase 2 / F-03, F-04), relative to Notes.md's directory.
    # Skip the Files line entirely if those annotations are missing -- better
    # silent than broken (B-3 review fix).
    json_p = result.get("jsonPath")
    md_p = result.get("mdPath")
    html_p = result.get("htmlPath")

    if (
        isinstance(json_p, str)
        and isinstance(md_p, str)
        and isinstance(html_p, str)
    ):
        def _rel_link(abs_path: str) -> str:
            abs_path_obj = Path(abs_path)
            rel = os.path.relpath(abs_path_obj, notes_path.parent)
            return "./" + rel.replace(os.sep, "/")

        lines.append(
            f"- **Files:** "
            f"[{_rel_link(json_p)}]({_rel_link(json_p)}) · "
            f"[{_rel_link(md_p)}]({_rel_link(md_p)}) · "
            f"[{_rel_link(html_p)}]({_rel_link(html_p)})"
        )
    if result.get("path"):
        lines.append(f"- **Binary:** `{result['path']}`")
    if result.get("file"):
        lines.append(f"- **Filename:** `{result['file']}`")
    if result.get("title"):
        lines.append(f"- **Title:** {result['title']}")
    if result.get("error"):
        lines.append(f"- **Error:** {result['error']}")

    with notes_path.open("a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def format_result_markdown(function_name: str, result: dict[str, Any]) -> str:
    """Format a function result as readable Markdown.

    Keeps the structure human-friendly: H1 with the function name,
    H2 sections for each logical group, fenced JSON for raw data,
    bullet lists for arrays.
    """
    lines: list[str] = [f"# {function_name}\n"]
    ts = _dt.datetime.now().isoformat(timespec="seconds")
    lines.append(f"_Generated: {ts}_\n")

    # ---- success / error block
    ok = result.get("success")
    if ok is True:
        lines.append("**✅ success**\n")
    elif ok is False:
        lines.append(f"**❌ failed** — {result.get('error', '')}\n")
    else:
        lines.append("\n")

    # ---- video_id (if present)
    if "video_id" in result:
        lines.append(f"**Video ID:** `{result['video_id']}`\n")

    # ---- main "value" fields
    skip = {"success", "error", "video_id", "_dir", "path", "file"}
    scalars: list[tuple[str, Any]] = []
    arrays: list[tuple[str, list[Any]]] = []
    nested: list[tuple[str, dict[str, Any]]] = []
    for k, v in result.items():
        if k in skip:
            continue
        if isinstance(v, list):
            arrays.append((k, v))
        elif isinstance(v, dict):
            nested.append((k, v))
        else:
            scalars.append((k, v))

    if scalars:
        lines.append("## Result\n")
        for k, v in scalars:
            lines.append(f"- **{k}:** `{v}`")
        lines.append("")

    if arrays:
        for k, v in arrays:
            lines.append(f"## {k}\n")
            for item in v:
                if isinstance(item, dict):
                    lines.append(format_dict_item(item))
                else:
                    lines.append(f"- `{item}`")
            lines.append("")

    if nested:
        for k, v in nested:
            lines.append(f"## {k}\n")
            for sk, sv in v.items():
                if isinstance(sv, (list, dict)):
                    lines.append(f"### {sk}\n")
                    lines.append("```json")
                    lines.append(json.dumps(sv, ensure_ascii=False, indent=2))
                    lines.append("```\n")
                else:
                    lines.append(f"- **{sk}:** `{sv}`")
            lines.append("")

    # ---- raw JSON dump at the bottom
    lines.append("## Raw JSON\n")
    lines.append("```json")
    clean = {k: v for k, v in result.items() if k != "_dir"}
    lines.append(json.dumps(clean, ensure_ascii=False, indent=2))
    lines.append("```")
    return "\n".join(lines) + "\n"


def format_dict_item(d: dict[str, Any]) -> str:
    """Format a single dict (e.g. one transcript snippet) as Markdown."""
    parts = [f"`{k}`={repr(v)}" for k, v in d.items()]
    return "- " + " · ".join(parts)


def write_result(
    session_id: str,
    function_name: str,
    result: dict[str, Any],
    request: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Persist ``result`` as JSON + Markdown + HTML in the canonical
    Resultset-Layout ``<session>/results/<sid>.<NN>result.{ext}`` and
    update Notes.md.  Returns the result annotated with file paths for
    the Baustein chat notification (Phase 2 / F-03, F-04, YT-03, YT-04).

    Layout (Spec YT-02..YT-06 + F-03 + F-04):
        <session_root>/results/<sid>.<NN>result.{json,md,html}
        <session_root>/Notes.md                              (aggregated)

    Drei Dateiansichten desselben logischen Ergebnisses zaehlen als EINE
    Sequenz; der naechste Call erhaelt NN+1.  Die Sequenznummer wird
    von ``next_function_index(session_id)`` BEREITGESTELLT -- das heisst:
    bei leerem Results-Verzeichnis liefert sie "01", nach einem
    vorhandenen ".01result.*" liefert sie "02".
    """
    if not session_id:
        # Without a session id we can't write anywhere; return the raw
        # result unchanged so the caller can still surface it.
        return result

    results_dir = get_results_dir(session_id)
    nn = next_function_index(session_id)
    json_path = results_dir / f"{session_id}.{nn}result.json"
    md_path = results_dir / f"{session_id}.{nn}result.md"
    html_path = results_dir / f"{session_id}.{nn}result.html"

    # YT-05 (Phase 4): track per-file write outcome so we can decide
    # the headline.success AFTER all three writes completed. Spec says:
    # "Erst NACH erfolgreichem Write aller 3 -> headline.success=true".
    # A failure in any single file must not silently produce a
    # success=true headline.
    write_errors: list[str] = []
    clean = {k: v for k, v in result.items() if k != "_dir"}

    # 1) JSON
    try:
        json_path.write_text(
            json.dumps(clean, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError as e:
        write_errors.append(f"json: {e}")

    # 2) Markdown
    md_text = format_result_markdown(function_name, clean)
    try:
        md_path.write_text(md_text, encoding="utf-8")
    except OSError as e:
        write_errors.append(f"md: {e}")

    # 3) HTML (standalone, mit eingebettetem Styling)
    try:
        html_path.write_text(
            format_result_html(function_name, clean, md_text),
            encoding="utf-8",
        )
    except OSError as e:
        write_errors.append(f"html: {e}")

    # YT-05: verify all three files are non-empty (spec: >=1 Byte each).
    for label, p in (("json", json_path), ("md", md_path), ("html", html_path)):
        try:
            if p.stat().st_size < 1:
                write_errors.append(f"{label}: empty")
        except OSError as e:
            write_errors.append(f"{label} stat: {e}")

    # 4) Annotate the result so _summary can derive NN from jsonPath
    #    (annotate even on failure so the UI can show intended paths).
    result["_dir"] = str(results_dir)        # legacy alias (now points to results/)
    result["jsonPath"] = str(json_path)
    result["mdPath"] = str(md_path)
    result["htmlPath"] = str(html_path)

    # YT-05: headline.success gate. If the upstream said success but any
    # of the three Resultset-files failed to write or came back empty,
    # flip success to false and append an explicit errorCode/Message
    # so the Baustein surfaces the persistence failure.
    if write_errors:
        existing_err = result.get("error") or ""
        joined = "; ".join(write_errors)
        if existing_err:
            result["error"] = f"{existing_err}; persistence: {joined}"
        else:
            result["error"] = f"persistence: {joined}"
        result["errorCode"] = "PERSISTENCE_INCOMPLETE"
        result["persistenceErrors"] = write_errors
        # Override success to False -- the canonical Resultset is
        # incomplete. The caller (HTTP / ZMQ) still returns the
        # annotated result so the UI can render the failure path.
        result["success"] = False

    # 5) Append to Notes.md (best-effort; never block on this)
    try:
        update_session_notes(session_id, function_name, result, request)
    except Exception as e:  # noqa: BLE001
        logger.warning("Notes.md update failed for %s: %s", session_id, e)

    return result


def read_session_notes(session_id: str) -> str | None:
    """Read the full Notes.md for a session (used by the Baustein's
    /api/chat/session/:id endpoint so the user can pull the log)."""
    p = get_session_dir(session_id) / "Notes.md"
    if not p.exists():
        return None
    return p.read_text(encoding="utf-8")


# ─── HTML rendering ──────────────────────────────────────────────────────

# Stylesheet embedded in every result.html so the file renders nicely
# when opened directly in a browser (no external dependencies).
_HTML_STYLE = """
:root {
  --bg: #0f1419;
  --panel: #161c24;
  --text: #d8dde6;
  --muted: #8a94a6;
  --accent: #ff8a3d;
  --link: #6ab7ff;
  --border: #2a323d;
  --ok: #5dd39e;
  --fail: #ff6b6b;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  padding: 32px;
  background: var(--bg);
  color: var(--text);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
               "Helvetica Neue", Arial, sans-serif;
  font-size: 15px;
  line-height: 1.55;
}
main {
  max-width: 880px;
  margin: 0 auto;
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 28px 32px;
}
header.result-head {
  border-bottom: 1px solid var(--border);
  padding-bottom: 12px;
  margin-bottom: 18px;
}
header.result-head h1 { margin: 0 0 4px 0; font-size: 22px; }
header.result-head .ts {
  color: var(--muted); font-size: 12px;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
}
.badge {
  display: inline-block; padding: 2px 8px; border-radius: 999px;
  font-size: 12px; font-weight: 600;
  background: rgba(93, 211, 158, 0.15); color: var(--ok);
}
.badge.fail {
  background: rgba(255, 107, 107, 0.15); color: var(--fail);
}
h2 { color: var(--accent); margin-top: 24px; font-size: 17px; }
h3 { color: var(--text); margin-top: 18px; font-size: 15px; }
a { color: var(--link); text-decoration: none; }
a:hover { text-decoration: underline; }
code {
  background: rgba(255, 255, 255, 0.06);
  padding: 1px 5px; border-radius: 3px;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 13px;
}
pre {
  background: rgba(0, 0, 0, 0.35);
  border: 1px solid var(--border);
  border-radius: 4px;
  padding: 12px;
  overflow-x: auto;
  font-size: 12px;
  line-height: 1.45;
}
ul, ol { padding-left: 22px; }
li { margin-bottom: 4px; }
hr { border: none; border-top: 1px solid var(--border); margin: 20px 0; }
img { max-width: 100%; border-radius: 4px; }
""".strip()


def format_result_html(
    function_name: str,
    result: dict[str, Any],
    md_text: str,
) -> str:
    """Render a standalone HTML file from the same Markdown that we
    wrote to ``result.md``.  The file has no external dependencies and
    opens directly in any modern browser.
    """
    # markdown→HTML; the markdown lib escapes <, >, & by default, which
    # gives us XSS safety for arbitrary yt-dlp / transcript payloads.
    body_html = _md.markdown(
        md_text,
        extensions=["fenced_code", "tables", "sane_lists"],
        output_format="html5",
    )
    ok = result.get("success")
    badge_html = (
        '<span class="badge">✅ success</span>'
        if ok
        else '<span class="badge fail">❌ failed</span>'
        if ok is False
        else ""
    )
    title = function_name
    ts = _dt.datetime.now().isoformat(timespec="seconds")
    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '  <meta charset="utf-8">\n'
        f"  <title>{title} — result</title>\n"
        f"  <style>{_HTML_STYLE}</style>\n"
        "</head>\n"
        "<body>\n"
        "  <main>\n"
        '    <header class="result-head">\n'
        f"      <h1>{title}</h1>\n"
        f'      <span class="ts">Generated {ts}</span> {badge_html}\n'
        "    </header>\n"
        f"    {body_html}\n"
        "  </main>\n"
        "</body>\n"
        "</html>\n"
    )