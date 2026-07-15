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

    # 6) Maintain session_readme.txt (v1.2.0, Phase 5) — service-agnostic
    #    human-readable overview of the session folder.  Best-effort;
    #    ``write_session_readme`` already catches its own errors, but we
    #    wrap it again so a regression in either layer can NEVER block
    #    the persistence pipeline.
    try:
        write_session_readme(session_id, function_name, result, request)
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "session_readme write failed for %s: %s", session_id, e,
        )

    return result


def read_session_notes(session_id: str) -> str | None:
    """Read the full Notes.md for a session (used by the Baustein's
    /api/chat/session/:id endpoint so the user can pull the log)."""
    p = get_session_dir(session_id) / "Notes.md"
    if not p.exists():
        return None
    return p.read_text(encoding="utf-8")


"""Helper code to insert into app/session_store.py (Phase 5 — session_readme)."""

# ---------------------------------------------------------------------------
# Session-Readme (v1.2.0, Phase 5) — service-agnostic human-readable overview
# ---------------------------------------------------------------------------
#
# Eine ``session_readme.txt`` wird beim ersten ``write_result``-Call
# angelegt und bei jedem weiteren Call vollstaendig neu geschrieben
# (atomic-write via temp+rename; gleiche Konvention wie Notes.md
# nur ohne Append-Verhalten).  Service-agnostisch: die Video-Context-
# Section erscheint nur, wenn ein YouTube-artiger Call erkannt wird
# (function_name in der YT-Set ODER URL enthaelt youtube.com/youtu.be);
# sonst faellt der Block auf den generischen Resource-Context zurueck
# (roher ``request``-Body ohne ``sessionId``).
#
# State lebt in einem Sidecar ``session_readme_meta.json`` neben der
# Readme -- so ist die Readme jederzeit aus dem Sidecar + aktuellem
# ``results/``-Listing rekonstruierbar.  Der Sidecar wird bei jedem
# Call ueberschrieben (read-modify-write auf kleiner Datei, akzeptabel
# weil parallel-loses Aufrufer-Muster im aktuellen write_result-Pfad).
#

# Filenames der beiden Readme-Artefakte (stabil pro Session).
_README_FILENAME = "session_readme.txt"
_README_META_FILENAME = "session_readme_meta.json"

# Function-Names, die einen YouTube-Video-Kontext implizieren.  Andere
# Services (z.B. me4-transkript, me4-splitter, me4-slides) rufen hier
# nicht mit auf und bekommen automatisch den generischen
# Resource-Context-Block.
_YT_FUNCTION_NAMES = frozenset({
    "get-metadata",
    "get-transcript",
    "get-comments",
    "download",
    "trigger-sm-produce",
    "process",
})

# Hosts, die als "YouTube-Video-Resource" zaehlen.  Case-insensitive,
# Subdomains ignoriert (matches ``m.youtube.com``).
_YT_HOST_HINTS = (
    "youtube.com",
    "youtu.be",
)


def _is_video_call(
    function_name: str,
    request: dict[str, Any] | None,
) -> bool:
    """True if this call is YouTube-video-related (renders Video-context).

    Two signals (OR-combined, weil nicht jeder Caller den function_name
    in die YT-Set eintraegt -- z.B. ein pipeline-internes ``process``
    vs. ein low-level ``download``):

      1. ``function_name`` ist in der YT-Set, ODER
      2. ``request.url`` enthaelt einen YouTube-Host.

    Alles andere faellt auf Resource-Context zurueck (service-agnostisch).
    """
    if function_name in _YT_FUNCTION_NAMES:
        return True
    if not request:
        return False
    url = str(request.get("url") or "").lower()
    if not url:
        return False
    return any(h in url for h in _YT_HOST_HINTS)


def _input_summary(request: dict[str, Any]) -> dict[str, Any]:
    """Extract a best-effort input summary from a request body.

    Strips secret-ish keys (``sessionId``, ``api_key``) and keeps only
    scalar values (str/int/float/bool) so the calls-table column stays
    one line per call.  Used by the readme calls table and by the
    Resource-context block (the latter takes the full request minus
    ``sessionId``).
    """
    skip = {"sessionId", "api_key"}
    out: dict[str, Any] = {}
    for k, v in request.items():
        if k in skip:
            continue
        if isinstance(v, (str, int, float, bool)):
            out[k] = v
    return out


def _format_input_column(input_dict: dict[str, Any]) -> str:
    """Render the input-dict as a one-line ``k=v`` summary for the table.

    Caps at 6 pairs to keep the table readable; trailing ``...`` when
    truncated.
    """
    if not input_dict:
        return "-"
    pairs = [f"{k}={v!r}" for k, v in list(input_dict.items())[:6]]
    line = " ".join(pairs)
    if len(input_dict) > 6:
        line += " ..."
    return line


def _new_readme_meta(session_id: str) -> dict[str, Any]:
    """Fresh sidecar-meta for the very first call in this session."""
    ts = _dt.datetime.now().isoformat(timespec="seconds")
    return {
        "service_id": settings.service_id,
        "service_version": settings.service_version,
        "session_id": session_id,
        "created_at": ts,
        "last_updated_at": ts,
        "calls": [],
        "video_context": None,
    }


def _load_readme_meta(path: Path) -> dict[str, Any]:
    """Load sidecar JSON; on corruption start fresh (logged warning).

    We deliberately don't try to recover from a corrupted sidecar by
    scanning ``results/`` -- the NN is recoverable but the function_name
    and request body are not, so a partial recovery would still be
    lossy.  Better to start fresh and let the next calls repopulate.
    """
    if not path.exists():
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("readme sidecar %s unreadable: %s -- starting fresh", path, e)
        return {}
    if not isinstance(loaded, dict):
        logger.warning("readme sidecar %s is not a dict: %r", path, type(loaded).__name__)
        return {}
    return loaded


def _atomic_write_text(path: Path, content: str) -> None:
    """Write ``content`` to ``path`` atomically (temp + ``os.replace``).

    LF line endings: we explicitly write ``content`` as-is, never
    converting; the helpers in this module build the text with ``\n``
    only.  On Windows, ``Path.write_text(..., encoding="utf-8",
    newline="\n")`` would force LF; on POSIX the default is already LF.
    """
    tmp = path.parent / f".{path.name}.tmp"
    try:
        tmp.write_text(content, encoding="utf-8", newline="\n")
        os.replace(tmp, path)
    finally:
        # Best-effort cleanup if rename didn't happen
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


# Tail regex for the trailing ``.NNresult.{ext}`` suffix on a resultset
# filename.  Strict ``_RESULT_RE`` (above) uses ``[^.]+`` for the sid segment
# which BREAKS whenever the session_id contains a literal ``.`` (e.g. a
# namespaced / video-ID-derived id like ``"abc.12345"``).  The trailing
# pattern is stable:  ``.NNresult.{json,md,html}`` regardless of what the
# sid segment contains.  Used by ``_current_nn_from_result`` as the
# fallback in PATH A (filesystem-anchored, deterministic).
_NN_TAIL_RE = re.compile(r"\.(\d{2})result\.(json|md|html)$")


def _current_nn_from_result(
    result: dict[str, Any],
    results_dir: Path | None = None,
    session_id: str | None = None,
) -> str:
    """Extract the NN that ``write_result`` just assigned (e.g. ``"01"``).

    Robust derivation (PATH A — deterministic + filesystem-anchored,
    selected over the cheaper regex-only path because the strict
    ``_RESULT_RE`` does not tolerate literal ``.`` in ``session_id``):

      1. Strict ``_RESULT_RE`` on ``result["jsonPath"]`` (fast path;
         works for plain alnum sid values).
      2. Tail-only ``_NN_TAIL_RE`` on the same basename (catches
         ``"abc.12345.07result.json"`` shapes where the strict regex
         cannot anchor the full filename).
      3. Filesystem fallback: scan ``results_dir`` for the highest NN
         across files whose name starts with ``f"{session_id}."`` and
         matches the tail pattern.  The just-written NN IS the highest
         NN on disk for this session, by definition (``write_result``
         always appends the next sequence number).

    Returns ``""`` when no annotation is present AND no matching file
    is on disk.  The caller (``write_session_readme``) substitutes
    ``"?"`` for backward compat.
    """
    # 1. Strict regex on jsonPath (fast path).
    json_path = result.get("jsonPath")
    if isinstance(json_path, str) and json_path:
        m = _RESULT_RE.match(Path(json_path).name)
        if m:
            return m.group("nn")
        # 2. Tail-only regex (sid may contain dots — strict regex fails).
        #    Use ``search()`` because the prefix ``<sid>.`` is variable-
        #    length and may contain ``.`` (which means ``match()`` won't
        #    anchor us at the tail).
        tail = _NN_TAIL_RE.search(Path(json_path).name)
        if tail:
            return tail.group(1)

    # 3. Filesystem fallback: scan results_dir for the highest NN of
    #    files belonging to this session.  Filter by name prefix
    #    ``"<session_id>."`` so cross-session contamination cannot
    #    leak into the NN cell.  Tolerates an OSError on dir scan
    #    (best-effort: a missing results_dir must not crash the readme
    #    writer — the outer try/except already covers this layer).
    if results_dir is not None and session_id:
        try:
            if results_dir.exists() and results_dir.is_dir():
                prefix = f"{session_id}."
                max_idx = 0
                for p in results_dir.iterdir():
                    if not p.is_file():
                        continue
                    if not p.name.startswith(prefix):
                        continue
                    tail = _NN_TAIL_RE.search(p.name)
                    if not tail:
                        continue
                    idx = int(tail.group(1))
                    if idx > max_idx:
                        max_idx = idx
                if max_idx > 0:
                    return f"{max_idx:02d}"
        except OSError as e:
            # Best-effort: a missing/unreadable results_dir is logged
            # here; never raise.
            logger.warning(
                "nn scan of %s for session=%s failed: %s",
                results_dir, session_id, e,
            )

    return ""


def _render_readme(meta: dict[str, Any], results_dir: Path) -> str:
    """Build the full readme text from sidecar meta + live results dir.

    Sections rendered (in order):
      1. H1 title + service metadata block (service id, version,
         session id, created-at, last-updated-at).
      2. ``## What this folder contains`` -- human-readable description
         of the layout (Notes.md, results/, this readme, sidecar JSON).
      3. ``## Calls`` -- table: NN | function_name | timestamp | input.
      4. ``## Video context`` -- ONLY when ``meta["video_context"]`` is
         set; URL + video_id + title.
      5. ``## Resource context`` -- ONLY when NO video-context; raw
         request of the LAST call minus ``sessionId``.
      6. ``## Files in results/`` -- ls -la-style lines (size + mtime
         + name), one per file.

    Sections 4 and 5 are mutually exclusive (service-agnostic contract:
    Video-Context faellt auf Resource-Context zurueck wenn nicht
    anwendbar).  Either-or, never both.
    """
    lines: list[str] = []
    sid = meta.get("session_id") or ""
    svc_id = meta.get("service_id") or settings.service_id
    svc_ver = meta.get("service_version") or settings.service_version
    created = meta.get("created_at") or ""
    updated = meta.get("last_updated_at") or ""

    # 1. Header
    lines.append(f"# Session `{sid}` -- README")
    lines.append("")
    lines.append(f"Service: `{svc_id}`  v`{svc_ver}`")
    lines.append(f"Session id: `{sid}`")
    lines.append(f"Created: `{created}`")
    lines.append(f"Last updated: `{updated}`")
    lines.append("")

    # 2. What this folder contains
    lines.append("## What this folder contains")
    lines.append("")
    lines.append(
        "This folder holds all artefacts produced by calls to "
        f"`{svc_id}` during the user's interaction with this session."
    )
    lines.append("")
    lines.append(
        "- `Notes.md` -- append-only log of every call (one H2 per "
        "call, with URL, success marker, and links to the result files)."
    )
    lines.append(
        "- `results/` -- the canonical resultset directory. Each call "
        "writes three file-views of the same logical result here, named "
        "`<session_id>.<NN>result.{json,md,html}`. Three file-views "
        "count as ONE sequence; the next call gets NN+1."
    )
    lines.append(
        "- `session_readme.txt` -- this file. A service-agnostic "
        "overview of the session: metadata, call history, file "
        "inventory, and (when applicable) video or resource context."
    )
    lines.append(
        "- `session_readme_meta.json` -- sidecar JSON with the same "
        "metadata in machine-readable form. Used to regenerate this "
        "readme after restarts."
    )
    lines.append("")

    # 3. Calls table
    lines.append("## Calls")
    lines.append("")
    calls = meta.get("calls") or []
    if calls:
        lines.append(
            "| NN  | function        | timestamp           "
            "| input                                      |"
        )
        lines.append(
            "|-----|-----------------|---------------------"
            "|--------------------------------------------|"
        )
        for c in calls:
            nn = str(c.get("nn") or "-").ljust(3)
            fn = str(c.get("function_name") or "-")
            ts = str(c.get("timestamp") or "-")
            inp = _format_input_column(c.get("input") or {})
            # Keep the table from blowing out by truncating function + input
            fn_disp = fn if len(fn) <= 15 else fn[:12] + "..."
            inp_disp = inp if len(inp) <= 42 else inp[:39] + "..."
            lines.append(f"| {nn} | {fn_disp:<15} | {ts:<19} | {inp_disp:<42} |")
        lines.append("")
    else:
        lines.append("_(no calls recorded yet)_")
        lines.append("")

    # 4. Video context (only if set)
    vc = meta.get("video_context") or {}
    rc = meta.get("resource_context") or {}
    if vc:
        lines.append("## Video context")
        lines.append("")
        if vc.get("url"):
            lines.append(f"URL: `{vc['url']}`")
        if vc.get("video_id"):
            lines.append(f"Video ID: `{vc['video_id']}`")
        if vc.get("title"):
            lines.append(f"Title: `{vc['title']}`")
        lines.append("")
    elif rc:
        # 5. Resource context (generic, service-agnostic fallback)
        lines.append("## Resource context")
        lines.append("")
        lines.append("Raw request body of the most recent call (minus `sessionId`):")
        lines.append("")
        for k, v in rc.items():
            lines.append(f"- `{k}`: `{v}`")
        lines.append("")

    # 6. Files in results/
    lines.append("## Files in `results/`")
    lines.append("")
    lines.append("Listing (size in bytes, mtime in ISO format):")
    lines.append("")
    if not results_dir.exists():
        lines.append("_(results/ directory does not exist yet)_")
        lines.append("")
    else:
        # Sort: regular files only, by name (stable order across calls)
        try:
            entries = sorted(
                (p for p in results_dir.iterdir() if p.is_file()),
                key=lambda p: p.name,
            )
        except OSError as e:
            lines.append(f"_(cannot list results/: {e})_")
            entries = []
        if not entries:
            lines.append("_(results/ is empty)_")
        else:
            for p in entries:
                try:
                    st = p.stat()
                    size = st.st_size
                    mtime = _dt.datetime.fromtimestamp(st.st_mtime).isoformat(
                        timespec="seconds"
                    )
                except OSError as e:
                    lines.append(f"  {p.name}  (stat failed: {e})")
                    continue
                lines.append(f"  {p.name}   {size} bytes   {mtime}")
        lines.append("")

    return "\n".join(lines)


def write_session_readme(
    session_id: str,
    function_name: str,
    result: dict[str, Any],
    request: dict[str, Any] | None = None,
) -> None:
    """Write/update ``session_readme.txt`` for the given session.

    The readme is a service-agnostic, human-readable overview of the
    session folder (Notes.md, results/, this readme itself, the sidecar
    JSON, plus a per-call table and a live listing of ``results/``).

    Behaviour:
      * First call for a session: creates both ``session_readme.txt``
        and the sidecar ``session_readme_meta.json`` from scratch.
      * Subsequent calls: reads the sidecar, appends the new call,
        rewrites the sidecar, and rewrites the readme in full.  The
        rewrite is atomic (temp + ``os.replace``), so a partial readme
        is never visible to readers.
      * Service-agnostic: ``## Video context`` appears only when a
        YouTube-style call is detected (``function_name`` in the YT set
        OR URL matches YouTube hostnames); otherwise a generic
        ``## Resource context`` block is rendered from the last call's
        request body.
      * Best-effort: ANY exception is caught, logged as a WARNING, and
        swallowed -- this helper MUST NEVER block the ``write_result``
        path.  ``write_result`` wraps the call in its own try/except
        belt-and-suspenders as well.

    Args:
        session_id: Session identifier.  Resolved through
            :func:`resolve_session_dir` so both canonical and legacy
            layouts are accepted.
        function_name: Function/tool name of the just-persisted call.
        result: Result dict from ``write_result`` (used to read
            ``jsonPath`` for the assigned NN, and to harvest
            ``video_id`` / ``title`` for the first metadata call).
        request: The original request body (used for the input-summary
            column and for the Resource-context block).
    """
    if not session_id:
        return

    try:
        base = resolve_session_dir(session_id)
        readme_path = base / _README_FILENAME
        meta_path = base / _README_META_FILENAME
        results_dir = base / "results"

        # 1. Load existing meta (or start fresh)
        meta = _load_readme_meta(meta_path)
        if not meta:
            meta = _new_readme_meta(session_id)

        ts_now = _dt.datetime.now().isoformat(timespec="seconds")
        meta["last_updated_at"] = ts_now

        # 2. Figure out which NN this call corresponds to.  After
        #    write_result has persisted the files, ``result["jsonPath"]``
        #    is the cheapest source of truth; fall back to scanning
        #    ``results_dir`` (PATH A: filesystem-anchored NN derivation,
        #    robust against ``.`` in session_id which breaks the strict
        #    result-set regex).
        nn = _current_nn_from_result(
            result, results_dir=results_dir, session_id=session_id,
        )
        if not nn:
            # Conservative fallback: take the highest NN currently on
            # disk + 0 -- we don't want to invent numbers here, so we
            # just skip the NN field rather than guess wrong.
            nn = "?"

        # 3. Build the input summary (skip secrets, scalars only)
        req = request or {}
        input_summary = _input_summary(req)

        # 4. Append the call record
        meta.setdefault("calls", []).append({
            "nn": nn,
            "function_name": function_name,
            "timestamp": ts_now,
            "input": input_summary,
        })

        # 5. Video-context promotion (first video call wins, never
        #    overwritten on subsequent calls -- spec says "from first
        #    metadata result").  We keep this in the sidecar so the
        #    Video-context section is stable across subsequent calls
        #    that don't carry the URL again.
        if _is_video_call(function_name, req):
            vc = meta.get("video_context") or {}
            url = req.get("url")
            vid = req.get("video_id") or result.get("video_id")
            title = result.get("title")
            if url and "url" not in vc:
                vc["url"] = url
            if vid and "video_id" not in vc:
                vc["video_id"] = vid
            if title and "title" not in vc:
                vc["title"] = title
            if vc:
                meta["video_context"] = vc
            # Once a video-context is established, drop any
            # resource-context the sidecar may have carried over from a
            # hypothetical pre-video call (defensive: shouldn't happen
            # in practice but keeps the sidecar consistent).
            if "resource_context" in meta:
                del meta["resource_context"]
        else:
            # Generic resource-context (service-agnostic): keep the
            # most-recent non-video request body, minus ``sessionId``,
            # so the readme can show what the user handed the service.
            rc: dict[str, Any] = {}
            for k, v in req.items():
                if k == "sessionId":
                    continue
                if isinstance(v, (str, int, float, bool)):
                    rc[k] = v
            if rc:
                meta["resource_context"] = rc
            # If the first call was non-video and a later call is
            # video, the video-context branch above clears the
            # resource-context; the sidecar converges to whichever
            # mode the latest call set.

        # 6. Render + atomic write
        text = _render_readme(meta, results_dir)
        _atomic_write_text(readme_path, text)
        _atomic_write_text(meta_path, json.dumps(meta, ensure_ascii=False, indent=2))
    except Exception as e:  # noqa: BLE001
        # Belt-and-suspenders: ``write_result`` also wraps us in
        # try/except, but we double-guard so a regression in the
        # write_result path can never crash the persistence pipeline.
        logger.warning(
            "session_readme write failed for session=%s function=%s: %s",
            session_id, function_name, e,
        )


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