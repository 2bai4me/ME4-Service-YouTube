r"""Tests fuer ``app.response_contract::build_summary`` + ``app.session_store.write_result``
(Spec YT-03, YT-04, F-03, F-04).

Vertrag (Spec Top-Level-Response):
  - ``dirAbsolute`` / ``filesSavedTo`` / ``resultsDir`` zeigen alle drei
    auf dasselbe ``<WORK_DIR>/sessions/<safe_sid>/results/``-Verzeichnis
    in Windows-URL-Form (forward-slashes, absolut, kein ``file://``).
  - ``files[]``: nur die Dateien des aktuellen Resultsets (regex-gefiltert
    via ``_RESULT_RE``); ``Notes.md``, Verzeichnisse und
    Vorgenger-Resultsets werden ausgeschlossen.
  - Zwei sequenzielle Calls in derselben Session duerfen sich nicht
    gegenseitig ueberschreiben (Regression-Garantie fuer Phase-1-Parser).
  - ``write_result`` schreibt tatsaechlich nach
    ``<session>/results/<sid>.<NN>result.{ext}`` und annotiert
    ``result["jsonPath"|"mdPath"|"htmlPath"]`` (Phase 2 / F-03, F-04).

Test-Strategie:
  * Reiner Logik-Test; ruft ``build_summary`` und ``write_result`` direkt
    auf.
  * Kein FastAPI-/yt_dlp-/zmq-Boot noetig.
  * ``tmp_path`` als ``settings.data_dir``-Root, damit die Pfad-Funktionen
    in der Sandbox schreiben.
  * Sequenzielle Regression-Tests benutzen den echten ``write_result``
    (statt ``_touch``-Simulation), damit ein zukuenftiger
    write_result-Regression-Defekt sofort sichtbar wird.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from app import session_store
from app.config import Settings
from app.response_contract import build_summary, detect_current_nn, list_resultset_files
from app.session_store import (
    _RESULT_RE,
    get_results_dir,
    get_session_dir,
    next_function_index,
    to_windows_url,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def isolated_data_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Setze ``settings.data_dir`` auf ``tmp_path`` fuer die Test-Sandbox."""
    session_store.settings.data_dir = str(tmp_path)
    return Settings(api_key="test", data_dir=str(tmp_path))


def _touch(p: Path, body: str = "{}") -> Path:
    """Hilfsfunktion: legt eine Datei (mit Body) an."""
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# Test 1: dirAbsolute points to results/, alias-identical to filesSavedTo
# ---------------------------------------------------------------------------


class TestDirAbsolutePointsToResults:
    """Spec YT-03 + F-03: ``dirAbsolute`` zeigt auf das ``results/``-Verzeichnis,
    nicht auf den Session-Root und nicht auf einen Per-Function-Subdir."""

    def test_dirabsolute_points_to_results(self, isolated_data_dir, tmp_path: Path):
        s = build_summary(
            "get-metadata",
            {"_dir": "<legacy-ignored>", "success": True, "title": "Hello"},
            session_id="sid-x",
        )
        assert s["dirAbsolute"] is not None
        # Auf POSIX: absoluter Posix-Pfad, der mit ``/results`` endet.
        assert s["dirAbsolute"].endswith("/results"), (
            f"dirAbsolute endet nicht auf /results: {s['dirAbsolute']!r}"
        )
        # Genauer Pfad: tmp_path / sessions / sid-x / results
        expected = (tmp_path / "sessions" / "sid-x" / "results").resolve()
        assert s["dirAbsolute"] == to_windows_url(expected)

    def test_dirabsolute_alias_filesavedto(self, isolated_data_dir):
        """Spec AC-4: dirAbsolute == filesSavedTo == resultsDir."""
        s = build_summary(
            "get-metadata", {"_dir": "<legacy>", "success": True},
            session_id="sid-x",
        )
        assert s["dirAbsolute"] == s["filesSavedTo"], (
            f"dirAbsolute und filesSavedTo divergieren: "
            f"{s['dirAbsolute']!r} vs {s['filesSavedTo']!r}"
        )
        assert s["dirAbsolute"] == s["resultsDir"], (
            f"dirAbsolute und resultsDir divergieren: "
            f"{s['dirAbsolute']!r} vs {s['resultsDir']!r}"
        )

    def test_session_dir_separate_from_results_dir(self, isolated_data_dir):
        """``sessionDir`` zeigt auf den Session-Root, separat von ``dirAbsolute``.

        Erlaubt UI-Tests, den Root zu inspizieren ohne das
        Results-Verzeichnis zu kennen.
        """
        s = build_summary(
            "get-metadata", {"_dir": "<legacy>"},
            session_id="sid-x",
        )
        assert "sessionDir" in s
        # Session-Root endet NICHT auf ``/results``.
        assert not s["sessionDir"].endswith("/results")
        # Aber er enthaelt die session_id.
        assert s["sessionDir"].endswith("/sid-x")
        # sessionDir ist der Parent von dirAbsolute.
        assert Path(s["dirAbsolute"]).parent == Path(s["sessionDir"])

    def test_paths_use_windows_url_form(self, isolated_data_dir):
        """Forward-Slashes, absolut, kein ``file://``-Praefix."""
        s = build_summary("get-metadata", {"_dir": "<legacy>"},
                          session_id="sid-x")
        for key in ("dirAbsolute", "filesSavedTo", "resultsDir",
                    "sessionDir", "jsonPath", "mdPath", "htmlPath"):
            v = s.get(key)
            assert v is not None, f"{key} fehlt"
            assert "\\" not in v, f"{key} hat Backslashes: {v!r}"
            assert not v.startswith("file://"), f"{key} hat file://: {v!r}"
            assert v.startswith("/") or (len(v) > 2 and v[1] == ":"), (
                f"{key} ist nicht absolut: {v!r}"
            )

    def test_path_fields_within_dirabsolute(self, isolated_data_dir):
        """jsonPath/mdPath/htmlPath liegen lexikalisch unter dirAbsolute."""
        s = build_summary("get-metadata", {"_dir": "<legacy>"},
                          session_id="sid-x")
        d = Path(s["dirAbsolute"])
        for key in ("jsonPath", "mdPath", "htmlPath"):
            p = Path(s[key])
            assert p.parent == d, (
                f"{key}={p!r} liegt nicht unter dirAbsolute={d!r}"
            )

    def test_empty_session_yields_empty_files(self, isolated_data_dir):
        """Leere Session: dirAbsolute zeigt auf results/, files=[] (nichts geschrieben)."""
        s = build_summary("get-metadata", {"_dir": "<legacy>"},
                          session_id="sid-empty")
        assert s["dirAbsolute"].endswith("/results")
        assert s["files"] == []
        assert s["listingError"] is None

    def test_no_session_id_returns_legacy_shape(self, isolated_data_dir):
        """Ohne session_id: legacy-Verhalten (nur func_dir-Felder, kein dirAbsolute)."""
        s = build_summary(
            "get-metadata",
            {"_dir": "/some/legacy/path"},
        )
        # Legacy-Aliase sind gesetzt
        assert s["filesSavedTo"] == "/some/legacy/path"
        # Neue Pflicht-Felder sind nicht erzwungen (koennen None sein).
        assert s.get("dirAbsolute") in (None, s.get("filesSavedTo"))


# ---------------------------------------------------------------------------
# Test 2: files[] lists only the current resultset (regex-filtered)
# ---------------------------------------------------------------------------


class TestFilesListFiltersToResultset:
    """Spec YT-04 + F-04: ``files[]`` enthaelt nur die Dateien des aktuellen
    Resultsets (``<sid>.<NN>result.{ext}``)."""

    def test_files_list_filters_to_resultset(self, isolated_data_dir):
        """Test-Setup wie in der Phase-2-Beschreibung:
            - Notes.md (raussen)
            - <sid>.01result.{json,md,html} (drin)
            - <sid>.02result.json (raussen, weil NN != aktuelles NN)
        Die kanonische ``<sid>.<NN>result.{ext}``-Schreibung kommt jetzt
        vom echten ``write_result`` (nicht mehr von ``_touch``-Setup).
        """
        from app.session_store import write_result
        sid = "sid-x"
        rd = get_results_dir(sid)
        # Setup exakt wie in der Aufgabenstellung: ein NN=01-Resultset
        # via write_result, plus Notes.md und ein .02result.json-Ablenker.
        r1 = write_result(
            sid, "get-metadata",
            {"success": True, "title": "NN01", "channel": "C"},
            request={"sessionId": sid, "url": "https://x"},
        )
        _touch(rd / "Notes.md", "# log")
        _touch(rd / f"{sid}.02result.json", "noise")  # Ablenker

        # build_summary wird mit dem write_result-Output gefuettert --
        # jsonPath/mdPath/htmlPath zeigen jetzt auf die echten Dateien.
        s = build_summary("get-metadata", r1, session_id=sid)

        # Erwartung: genau die 3 Dateien fuer NN=01.
        names = sorted(f["name"] for f in s["files"])
        assert names == sorted([
            f"{sid}.01result.html",
            f"{sid}.01result.json",
            f"{sid}.01result.md",
        ]), f"unerwartete files[]: {names}"
        assert len(s["files"]) == 3
        # Notes.md darf NICHT drin sein.
        assert not any(f["name"] == "Notes.md" for f in s["files"])
        # .02result.json (Ablenker) darf NICHT drin sein.
        assert not any(f["name"].endswith(".02result.json") for f in s["files"])

    def test_files_excludes_subdirectories(self, isolated_data_dir):
        """Verzeichnisse (z.B. legacy per-Function-Subdirs) zaehlen nicht."""
        sid = "sid-x"
        rd = get_results_dir(sid)
        # Legacy-Subdir anlegen
        legacy_subdir = rd / "01-get-metadata"
        legacy_subdir.mkdir()
        (legacy_subdir / "result.json").write_text("{}", encoding="utf-8")

        result = {
            "jsonPath": "<not-a-real-file-just-for-NN-extraction>",
        }
        # ``detect_current_nn`` wird mit jsonPath versuchen, dort eine NN
        # zu extrahieren; das schlaegt fehl, also Fallback-Scan.
        s = build_summary("get-metadata", result, session_id=sid)
        # Fallback liefert None (keine Files), dann next_function_index -> "01".
        # Filter auf NN=01; keine Datei matcht.
        assert s["files"] == []

    def test_files_excludes_notes_md_and_random_files(self, isolated_data_dir):
        """Notes.md und beliebige andere Dateien werden ignoriert."""
        sid = "sid-x"
        rd = get_results_dir(sid)
        _touch(rd / "Notes.md", "# log")
        _touch(rd / "random.txt", "irrelevant")
        _touch(rd / ".DS_Store", "")
        # Plus das kanonische Resultset fuer NN=01
        for ext in ("json", "md", "html"):
            _touch(rd / f"{sid}.01result.{ext}")
        result = {"jsonPath": str(rd / f"{sid}.01result.json")}
        s = build_summary("get-metadata", result, session_id=sid)
        names = {f["name"] for f in s["files"]}
        assert "Notes.md" not in names
        assert "random.txt" not in names
        assert ".DS_Store" not in names
        assert names == {
            f"{sid}.01result.html",
            f"{sid}.01result.json",
            f"{sid}.01result.md",
        }

    def test_files_excludes_foreign_session_files(self, isolated_data_dir):
        """Fremde Sessions im selben results/-Verzeichnis werden ignoriert
        (Defensiv-Check auf ``<sid>``-Segment)."""
        sid = "sid-y"
        rd = get_results_dir(sid)
        # sid-x hat bereits Resultat fuer NN=05.
        for ext in ("json", "md", "html"):
            _touch(rd / f"sid-x.05result.{ext}")
        # sid-y hat Resultat fuer NN=02.
        for ext in ("json", "md", "html"):
            _touch(rd / f"sid-y.02result.{ext}")
        # _summary fuer sid-y -> muss NN=02 (oder naechstes freies) nutzen,
        # NICHT sid-x.05 mitzaehlen.
        result = {"jsonPath": str(rd / f"sid-y.02result.json")}
        s = build_summary("get-metadata", result, session_id=sid)
        names = {f["name"] for f in s["files"]}
        assert not any(n.startswith("sid-x.") for n in names), (
            f"sid-x-Dateien landeten in sid-y-Listing: {names}"
        )
        assert names == {
            f"sid-y.02result.html",
            f"sid-y.02result.json",
            f"sid-y.02result.md",
        }

    def test_files_have_required_fields(self, isolated_data_dir):
        """Jedes Element in ``files[]`` hat ``name``, ``size``, ``mtimeMs``."""
        sid = "sid-x"
        rd = get_results_dir(sid)
        _touch(rd / f"{sid}.01result.json", '{"k":1}')
        result = {"jsonPath": str(rd / f"{sid}.01result.json")}
        s = build_summary("get-metadata", result, session_id=sid)
        assert len(s["files"]) == 1
        f = s["files"][0]
        assert set(f.keys()) == {"name", "size", "mtimeMs"}
        assert f["name"] == f"{sid}.01result.json"
        assert f["size"] >= 7  # '{"k":1}'.__len__() = 7
        assert isinstance(f["mtimeMs"], int)
        assert f["mtimeMs"] > 0


# ---------------------------------------------------------------------------
# Test 3: Regression - sequenzielle Resultsets, kein Overwrite
# ---------------------------------------------------------------------------


class TestSequentialResultsNoOverwrite:
    """Reproduziert das Kern-Bug-Symptom aus Phase 1: zwei sequenzielle
    Aufrufe in derselben Session erzeugen ``.01result.*`` und
    ``.02result.*``, ohne dass ``.01`` ueberschrieben wird.

    Dieser Test geht ueber ``write_result`` hinaus -- er simuliert die
    Writes direkt, weil Phase 2 noch nicht in den ``write_result``-Pfad
    eingreift.  Er beweist aber: die Pfad-/Listing-Kontrakte funktionieren
    konsistent fuer NN=01 und NN=02."""

    def test_sequential_results_no_overwrite(self, isolated_data_dir, tmp_path: Path):
        """Zwei echte ``write_result``-Calls erzeugen ``.01result.*`` und
        ``.02result.*`` ohne dass ``.01`` ueberschrieben wird
        (Regression-Schutz Phase 1 + Phase 2).

        B-2 Cross-Review: vorher wurde das Schreiben per ``_touch``
        simuliert; jetzt fahren wir den echten ``write_result``-Pfad --
        damit faengt dieser Test auch Regression-Defekte in
        ``write_result`` selbst ab.
        """
        from app.session_store import write_result
        sid = "sid-x"
        rd = get_results_dir(sid)
        assert rd.exists()

        # --- Aufruf 1: next_function_index liefert "01" ---
        idx1 = next_function_index(sid)
        assert idx1 == "01"
        result1 = write_result(
            sid, "get-metadata",
            {"success": True, "title": "Erster Call", "channel": "TestChannel"},
            request={"sessionId": sid, "url": "https://x"},
        )
        s1 = build_summary("get-metadata", result1, session_id=sid)

        assert s1["dirAbsolute"].endswith("/results"), (
            f"dirAbsolute endet nicht auf /results: {s1['dirAbsolute']!r}"
        )
        names1 = sorted(f["name"] for f in s1["files"])
        assert names1 == sorted([
            f"{sid}.01result.html",
            f"{sid}.01result.json",
            f"{sid}.01result.md",
        ]), f"NN=01 files[] unvollstaendig: {names1}"

        # --- Aufruf 2: next_function_index liefert "02" ---
        idx2 = next_function_index(sid)
        assert idx2 == "02", (
            f"Parser-Bug: zweiter Aufruf liefert {idx2!r}, nicht '02'. "
            "Dann wuerde das naechste Write das alte .01result.* ueberschreiben."
        )
        result2 = write_result(
            sid, "get-metadata",
            {"success": True, "title": "Zweiter Call", "channel": "TestChannel"},
            request={"sessionId": sid, "url": "https://y"},
        )
        s2 = build_summary("get-metadata", result2, session_id=sid)

        assert s2["dirAbsolute"] == s1["dirAbsolute"], (
            "dirAbsolute darf sich zwischen Aufrufen nicht aendern"
        )
        names2 = sorted(f["name"] for f in s2["files"])
        assert names2 == sorted([
            f"{sid}.02result.html",
            f"{sid}.02result.json",
            f"{sid}.02result.md",
        ]), f"NN=02 files[] unvollstaendig: {names2}"
        # NN=01 darf nicht mehr in s2 auftauchen -- es ist ein "Vorgaenger".
        assert not any(".01result" in n for n in names2), (
            f"NN=01 (Vorgaenger) taucht in NN=02-Listing auf: {names2}"
        )

        # --- Beide Resultsets existieren physisch, keine Datei ueberschrieben ---
        for nn, marker in (("01", "Erster Call"), ("02", "Zweiter Call")):
            for ext in ("json", "md", "html"):
                p = rd / f"{sid}.{nn}result.{ext}"
                assert p.exists(), f"{p.name} fehlt -- wurde ueberschrieben?"
                body = p.read_text(encoding="utf-8")
                assert marker in body, (
                    f"{p.name} enthaelt nicht den erwarteten Resultset-"
                    f"Marker '{marker}' -- wurde vermutlich ueberschrieben."
                )

    def test_notes_md_links_resolve_after_write_result(
        self, isolated_data_dir, tmp_path: Path
    ):
        """Nach einem echten ``write_result`` muessen alle Notes.md-Datei-Links
        tatsaechlich auf existierende Dateien im results/-Verzeichnis zeigen.

        Regression gegen B-3: vor dem Fix zeigte Notes.md auf
        ``./results/result.json``, weil ``update_session_notes`` aus
        ``Path(result['_dir']).name`` (jetzt ``results``) plus hard-coded
        ``/result.{ext}`` zusammenbaute -- aber nach der write_result-Migration
        heissen die Dateien ``<sid>.<NN>result.{ext}``.
        """
        from app.session_store import write_result
        sid = "probe-sid"
        notes_path = get_session_dir(sid) / "Notes.md"

        write_result(
            sid, "get-metadata",
            {"success": True, "title": "Probe Call"},
            request={"sessionId": sid, "url": "https://x"},
        )
        write_result(
            sid, "get-comments",
            {"success": True, "title": "Probe Call 2"},
            request={"sessionId": sid, "url": "https://x"},
        )

        assert notes_path.exists(), "Notes.md sollte nach write_result existieren"
        notes_text = notes_path.read_text(encoding="utf-8")

        # Regex: alle Markdown-Links der Form ([label](...)) deren Label
        # auf .json/.md/.html endet.  Konkrete Files haben Form
        # ``<sid>.<NN>result.{ext}`` -- der Label hier ist
        # ``./results/<sid>.<NN>result.{ext}``, also reicht eine
        # Extension-Sensitivitaet; die NN-Progression pruefen wir unten
        # explizit.
        link_re = re.compile(
            r"\[([^\s\]]+\.(?:json|md|html))\]\(([^)]+)\)"
        )
        matches = link_re.findall(notes_text)
        assert matches, (
            "Notes.md enthaelt keine .result.{ext}-Markdown-Links; "
            "B-3-Fix verfehlt?"
        )

        notes_dir = notes_path.parent
        for displayed, target in matches:
            # Markdown-Links sind relativ zu Notes.md.
            target_abs = (notes_dir / target.lstrip("./")).resolve()
            assert target_abs.exists(), (
                f"Notes.md-Link ist broken: '{displayed}' -> '{target}' "
                f"(expected {target_abs})"
            )
            # Dateinamen enthalten den echten Resultset-Pfad -- nicht
            # ``results/result.json`` (das war der B-3-Bug).  Erwartet wird
            # ``<sid>.<NN>result.{{ext}}`` irgendwo im Link-Ziel -- die
            # Position ist frei (kann mit oder ohne fuehrendem ``.`` sein).
            assert (
                f"{sid}.01result." in target
                or f"{sid}.02result." in target
            ), (
                f"Notes.md-Link zeigt auf falschen Namen (B-3 wieder?): "
                f"'{target}' -- sollte '<sid>.<NN>result.{{ext}}' enthalten"
            )

    def test_three_consecutive_resultsets_stay_disjoint(self, isolated_data_dir):
        """Stressprobe: drei sequenzielle ``write_result``-Calls, jedes
        Resultset isoliert (kein Overwrite, kein Vermischen)."""
        from app.session_store import write_result
        sid = "sid-x"
        rd = get_results_dir(sid)
        for expected, marker in (("01", "Call A"), ("02", "Call B"), ("03", "Call C")):
            idx = next_function_index(sid)
            assert idx == expected
            r = write_result(
                sid, "get-metadata",
                {"success": True, "title": marker},
                request={"sessionId": sid, "url": f"https://{marker.lower().replace(' ', '')}"},
            )
            s = build_summary("get-metadata", r, session_id=sid)
            names = sorted(f["name"] for f in s["files"])
            assert names == sorted([
                f"{sid}.{idx}result.html",
                f"{sid}.{idx}result.json",
                f"{sid}.{idx}result.md",
            ]), f"Listing fuer NN={idx} falsch: {names}"
        # Alle neun Dateien muessen physisch existieren und korrekt
        # getaggt sein (kein Ueberschreiben).
        for nn, marker in (("01", "Call A"), ("02", "Call B"), ("03", "Call C")):
            for ext in ("json", "md", "html"):
                p = rd / f"{sid}.{nn}result.{ext}"
                assert p.exists(), f"{p.name} fehlt"
                body = p.read_text(encoding="utf-8")
                assert marker in body, (
                    f"{p.name} enthaelt nicht den erwarteten Marker "
                    f"'{marker}' -- wurde ueberschrieben?"
                )

    def test_listing_path_inside_dirabsolute(self, isolated_data_dir):
        """Auch fuer zwei sequenzielle Resultsets (via ``write_result``)
        liegen ``jsonPath``/``mdPath``/``htmlPath`` jeweils unterhalb
        ``dirAbsolute``."""
        from app.session_store import write_result
        sid = "sid-x"

        for call_no in (1, 2):
            r = write_result(
                sid, "get-metadata",
                {"success": True, "title": f"Call {call_no}"},
                request={"sessionId": sid, "url": f"https://x{call_no}"},
            )
            s = build_summary("get-metadata", r, session_id=sid)
            d = Path(s["dirAbsolute"])
            for key in ("jsonPath", "mdPath", "htmlPath"):
                p = Path(s[key])
                assert p.parent == d, (
                    f"Call {call_no}: {key}={p!r} liegt nicht unter "
                    f"dirAbsolute={d!r}"
                )


# ---------------------------------------------------------------------------
# Bonus: detect_current_nn + list_resultset_files (sanity)
# ---------------------------------------------------------------------------


class TestDetectCurrentNN:
    """Direkttests auf den NN-Detektor (ohne den vollen build_summary-Pfad)."""

    def test_nn_from_jsonpath(self, isolated_data_dir):
        sid = "sid-x"
        rd = get_results_dir(sid)
        for ext in ("json", "md", "html"):
            _touch(rd / f"{sid}.42result.{ext}")
        result = {"jsonPath": str(rd / f"{sid}.42result.json")}
        assert detect_current_nn(sid, result) == "42"

    def test_nn_from_mdpath_when_no_jsonpath(self, isolated_data_dir):
        sid = "sid-x"
        rd = get_results_dir(sid)
        _touch(rd / f"{sid}.07result.md")
        result = {"mdPath": str(rd / f"{sid}.07result.md")}
        assert detect_current_nn(sid, result) == "07"

    def test_nn_falls_back_to_max_existing(self, isolated_data_dir):
        sid = "sid-x"
        rd = get_results_dir(sid)
        # Kein Pfad in result, aber Dateien existieren.
        for ext in ("json", "md", "html"):
            _touch(rd / f"{sid}.11result.{ext}")
        assert detect_current_nn(sid, {}) == "11"

    def test_nn_returns_none_when_empty(self, isolated_data_dir):
        sid = "sid-empty"
        get_results_dir(sid)  # erzeugt das Verzeichnis
        assert detect_current_nn(sid, {}) is None


class TestListResultsetFiles:
    """Direkttests auf den File-Lister."""

    def test_returns_empty_on_missing_dir(self, tmp_path: Path):
        nonexistent = tmp_path / "no-such-dir"
        files, err = list_resultset_files(nonexistent, "sid-x", "01")
        assert files == []
        assert err is not None

    def test_returns_only_matching_nn(self, isolated_data_dir):
        sid = "sid-x"
        rd = get_results_dir(sid)
        for nn in ("01", "02"):
            for ext in ("json", "md", "html"):
                _touch(rd / f"{sid}.{nn}result.{ext}")
        _touch(rd / "Notes.md")
        _touch(rd / f"{sid}.01result.bak")  # kaputte Ext
        files, err = list_resultset_files(rd, sid, "01")
        assert err is None
        names = sorted(f["name"] for f in files)
        assert names == sorted([
            f"{sid}.01result.html",
            f"{sid}.01result.json",
            f"{sid}.01result.md",
        ])
        # Backup-Datei mit falscher Extension muss draussen sein.
        assert not any(n.endswith(".bak") for n in names)
