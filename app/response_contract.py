r"""Top-Level-Response-Vertrag fuer ME4-S-youtube (Spec YT-03, F-03, F-04).

Dieses Modul enthaelt die reinen Datenhelfer ohne FastAPI-Abhaengigkeit,
damit sie isoliert testbar sind.  ``app.http_api`` reicht nur noch die
Request-Parameter durch.

Vertrag (Spec Top-Level-Response + YT-03):
    * ``dirAbsolute`` / ``filesSavedTo`` / ``resultsDir``: alle drei zeigen
      auf das gleiche Results-Verzeichnis
      ``<WORK_DIR>/sessions/<safe_sid>/results/`` in Windows-URL-Form
      (forward-slashes, absolut, kein ``file://``).
    * ``sessionDir`` (optional): Session-Root fuer UI-Tests.
    * ``jsonPath`` / ``mdPath`` / ``htmlPath``: absolute Pfade zu den
      drei kanonischen Resultset-Dateien ``<sid>.<NN>result.{ext}``.
    * ``files``: echtes Listing des Resultsets, gefiltert per
      ``_RESULT_RE`` auf das aktuelle ``NN`` (kein ``Notes.md``, keine
      Verzeichnisse, keine Vorgenger-Resultsets).
    * ``listingError``: ``None`` oder Fehler-String.
    * ``headline`` / ``function``: wie bisher.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from app.session_store import (
    _RESULT_RE,
    get_results_dir,
    get_session_dir,
    next_function_index,
    to_windows_url,
)


def detect_current_nn(session_id: str, result: dict) -> "str | None":
    """Bestimme die Sequenz-Nummer ``NN`` des aktuellen Resultsets.

    Strategie (in Reihenfolge):
      1. Wenn ``result`` ein Feld ``jsonPath`` / ``mdPath`` / ``htmlPath``
         enthaelt, das auf das kanonische Pattern
         ``<sid>.<NN>result.{json,md,html}`` matched, wird ``NN`` daraus
         extrahiert (Phase 4 wird diese Felder in ``write_result`` setzen).
      2. Sonst: hoechste existierende Sequenz ``NN`` fuer ``session_id``
         aus dem Results-Verzeichnis lesen. Liefert ``None``, wenn
         noch gar keine Datei dort liegt.
      3. Sonst (kein Pfad, keine existierenden Files): ``None``.

    Diese Funktion ruft **nicht** ``next_function_index`` auf, weil die
    das naechste freie ``NN+1`` liefert. Fuer die ``files[]``-Filterung
    brauchen wir aber das NN, das *gerade geschrieben wurde* (oder das
    einzige existierende). Wenn der Aufrufer noch kein Write gemacht
    hat, ist die Liste halt leer -- das ist korrekt (kein 500).
    """
    for key in ("jsonPath", "mdPath", "htmlPath"):
        raw = result.get(key)
        if not raw:
            continue
        try:
            m = _RESULT_RE.match(Path(raw).name)
        except (TypeError, ValueError):
            continue
        if m and m.group("sid") == session_id:
            return m.group("nn")
    if not session_id:
        return None
    try:
        results_dir = get_results_dir(session_id)
    except Exception:
        return None
    max_nn = None
    for p in results_dir.iterdir():
        if not p.is_file():
            continue
        m = _RESULT_RE.match(p.name)
        if not m or m.group("sid") != session_id:
            continue
        n = int(m.group("nn"))
        if max_nn is None or n > max_nn:
            max_nn = n
    return f"{max_nn:02d}" if max_nn is not None else None


def list_resultset_files(results_dir_native, session_id, nn):
    """Liste der Dateien des aktuellen Resultsets ``<sid>.<NN>result.{ext}``.

    Filterung:
      * Dateien (keine Verzeichnisse, keine ``Notes.md``, keine
        Vorgenger-Resultsets mit anderer ``NN``).
      * Regex-Match ``_RESULT_RE`` auf den Filename.
      * ``<sid>``-Segment muss zur aufrufenden ``session_id`` passen
        (Defensiv-Check, wie in ``next_function_index``).

    Liefert ``({name, size, mtimeMs}, listing_error_or_None)``. Bei
    einem Lese-Fehler wird ``[]`` und ein Fehler-String zurueckgegeben;
    die Response bleibt damit gueltig (kein 500).
    """
    files = []
    try:
        entries = sorted(results_dir_native.iterdir(), key=lambda p: p.name)
    except (FileNotFoundError, PermissionError, OSError) as e:
        return files, str(e)
    for p in entries:
        if not p.is_file():
            continue
        m = _RESULT_RE.match(p.name)
        if not m:
            continue
        if m.group("sid") != session_id or m.group("nn") != nn:
            continue
        try:
            st = p.stat()
        except OSError:
            continue
        files.append({
            "name": p.name,
            "size": st.st_size,
            "mtimeMs": int(st.st_mtime * 1000),
        })
    return files, None


def build_summary(function_name, result, session_id=""):
    """Build the top-level response for a service function call.

    Vertrag (Spec YT-03 + Top-Level-Response):
      - ``dirAbsolute`` / ``filesSavedTo``: das flache Results-Verzeichnis
        ``<session>/results/`` (Windows-URL-Form, forward-slashes,
        absolut, kein ``file://``).
      - ``resultsDir``: Legacy-Alias, identisch zu ``dirAbsolute``.
      - ``sessionDir`` (optional): Session-Root (fuer UI-Tests).
      - ``jsonPath`` / ``mdPath`` / ``htmlPath``: absolute Pfade zu den
        drei kanonischen Resultset-Dateien ``<sid>.<NN>result.{ext}``.
      - ``files``: echtes Listing des Resultsets, gefiltert per
        ``_RESULT_RE`` auf das aktuelle ``NN``.
      - ``listingError``: ``None`` oder Fehler-String.
      - ``headline`` / ``function``: wie bisher.

    ``session_id`` wird vom Aufrufer durchgereicht. Ohne ``session_id``
    (z.B. Aufrufer ohne Persistenz) wird ``dirAbsolute`` aus dem legacy
    ``result._dir`` abgeleitet -- die neuen Pflicht-Felder sind in
    diesem Fall ``None`` bzw. leer.
    """
    headline = {
        k: v for k, v in result.items()
        if k in {"success", "title", "channel", "snippet_count", "count", "file"}
        and v not in (None, "", [])
    }

    # --- ohne session_id: legacy-Verhalten (nur func_dir-Felder)
    if not session_id:
        func_dir = result.get("_dir", "")
        return {
            "filesSavedTo": func_dir or None,
            "jsonPath": str(Path(func_dir) / "result.json") if func_dir else None,
            "mdPath": str(Path(func_dir) / "result.md") if func_dir else None,
            "headline": headline,
            "function": function_name,
        }

    # --- Pfad-Aufloesung
    listing_error = None
    try:
        results_dir_native = get_results_dir(session_id)
    except Exception as e:  # noqa: BLE001
        results_dir_native = None
        listing_error = str(e)

    session_dir_native = None
    try:
        session_dir_native = get_session_dir(session_id)
    except Exception:
        session_dir_native = None

    # --- NN des aktuellen Resultsets bestimmen
    nn = detect_current_nn(session_id, result)
    if nn is None:
        # Kein Pfad in result, keine existierenden Files.
        # Wir nutzen dann ``next_function_index`` als "next-NN" -- das ist
        # die NN, mit der der Aufruf *schreiben wird* (Phase 4-Pfad).
        # Aktuell (Phase 2) bleibt files[] dann leer, weil die Datei
        # noch nicht existiert. Das ist akzeptabel: Vertrag steht, Phase 4
        # befuellt ihn.
        nn = next_function_index(session_id)
        # Achtung: ``next_function_index`` gibt bereits einen
        # 2-stelligen String zurueck (Phase 1 / NB-3) -- KEIN
        # ``int(nn)+1`` oder ``f"{nn:02d}"`` drauf anwenden!

    files = []
    if results_dir_native is not None and nn is not None:
        files, listing_err = list_resultset_files(results_dir_native, session_id, nn)
        if listing_err is not None and listing_error is None:
            listing_error = listing_err

    # --- Top-Level Response
    if results_dir_native is not None and nn is not None:
        dir_absolute_str = to_windows_url(results_dir_native)
        json_path_str = to_windows_url(
            results_dir_native / f"{session_id}.{nn}result.json"
        )
        md_path_str = to_windows_url(
            results_dir_native / f"{session_id}.{nn}result.md"
        )
        html_path_str = to_windows_url(
            results_dir_native / f"{session_id}.{nn}result.html"
        )
    else:
        dir_absolute_str = None
        json_path_str = None
        md_path_str = None
        html_path_str = None

    session_dir_str = (
        to_windows_url(session_dir_native)
        if session_dir_native is not None
        else None
    )

    response = {
        "filesSavedTo": dir_absolute_str,
        "resultsDir": dir_absolute_str,
        "dirAbsolute": dir_absolute_str,
        "jsonPath": json_path_str,
        "mdPath": md_path_str,
        "htmlPath": html_path_str,
        "files": files,
        "listingError": listing_error,
        "headline": headline,
        "function": function_name,
    }
    if session_dir_str is not None:
        response["sessionDir"] = session_dir_str
    return response
