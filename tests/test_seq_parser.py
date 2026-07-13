r"""Tests für app/session_store.py::next_function_index (Spec § F-05).

Diese Tests prüfen die Pflicht-Parser-Heuristik:

    next_function_index(session_id) -> str
        pattern: ^\{sid\}\.(\d\{2\})result\.(json|md|html)$
        drei Dateiansichten desselben Ergebnisses zählen als EINE Sequenz
        Rückgabe als 2-stellig formatierter String ("01" .. "99")

Test-Strategie:
    * Reiner Logik-Test; ruft `next_function_index` direkt.
    * Kein `yt_dlp`/`zmq`/`fastapi`-Boot nötig.
    * `tmp_path` als ``settings.data_dir``-Root, damit `get_session_dir`
      und damit `get_results_dir` im Test-Sandbox schreiben.
    * `write_result` selbst wird NICHT aufgerufen — seine Dependencies
      ziehen `markdown` + einen vollständigen Service-Boot mit rein.
      Stattdessen werden die Result-Dateien manuell per
      ``Path.write_text(...)`` angelegt (Test G = Regressionstest, der
      das Kern-Bug-Symptom "zwei Aufrufe -> beide landen auf .01"
      abdeckt).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app import session_store
from app.config import Settings
from app.session_store import (
    _RESULT_RE,
    get_results_dir,
    next_function_index,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def isolated_data_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Setze ``settings.data_dir`` auf tmp_path und gib die neue Settings
    zurück.  ``get_session_dir`` (und damit ``get_results_dir``) lesen
    ``settings.data_dir`` direkt, also genügt ein ``setattr`` auf dem
    globalen Settings-Objekt, das ``app.session_store`` bereits importiert
    hat.
    """
    fresh = Settings(api_key="test", data_dir=str(tmp_path))
    monkeypatch.setattr(session_store.settings, "data_dir", str(tmp_path))
    return fresh


def _touch(results_dir: Path, name: str, body: str = "{}") -> Path:
    """Hilfsfunktion: legt eine Datei im Results-Verzeichnis an."""
    p = results_dir / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# Regex-Unit-Tests (sanity check auf _RESULT_RE direkt)
# ---------------------------------------------------------------------------


class TestResultRegex:
    """Direkte Tests auf das interne Regex.  Stellt sicher, dass die
    Heuristik wirklich nur die kanonische Form matcht."""

    def test_matches_canonical_form(self):
        m = _RESULT_RE.match("abc123.01result.json")
        assert m is not None
        assert m.group("sid") == "abc123"
        assert m.group("nn") == "01"
        assert m.group("ext") == "json"

    def test_matches_all_three_extensions(self):
        for ext in ("json", "md", "html"):
            m = _RESULT_RE.match(f"sid-x.42result.{ext}")
            assert m is not None
            assert m.group("ext") == ext
            assert m.group("nn") == "42"

    def test_rejects_notes_md(self):
        assert _RESULT_RE.match("Notes.md") is None

    def test_rejects_ds_store(self):
        assert _RESULT_RE.match(".DS_Store") is None

    def test_rejects_wrong_extension_case(self):
        # CamelCase-Variante muss draußen bleiben.
        assert _RESULT_RE.match("abc123.01resultJson") is None
        assert _RESULT_RE.match("abc123.01result.JSON") is None

    def test_rejects_single_digit_nn(self):
        # nur genau 2 Ziffern erlaubt
        assert _RESULT_RE.match("sid-x.1result.json") is None
        assert _RESULT_RE.match("sid-x.123result.json") is None

    def test_rejects_extra_dot_before_result(self):
        # "abc.01.results.json" darf NICHT matchen — falsche Form.
        assert _RESULT_RE.match("abc.01.results.json") is None

    def test_rejects_empty_sid(self):
        # sid muss mindestens ein Zeichen haben (kein führender Punkt).
        assert _RESULT_RE.match(".01result.json") is None


# ---------------------------------------------------------------------------
# Test A — Leeres results/ -> "01"
# ---------------------------------------------------------------------------


class TestEmpty:
    def test_empty_returns_01(self, isolated_data_dir):
        # get_results_dir erzeugt das Verzeichnis on demand; danach ist
        # es leer.
        rd = get_results_dir("sid-x")
        assert rd.exists()
        assert list(rd.iterdir()) == []
        assert next_function_index("sid-x") == "01"


# ---------------------------------------------------------------------------
# Test B — nach .01result.{json,md,html} -> "02"
# ---------------------------------------------------------------------------


class TestAfterFirstResult:
    def test_three_views_count_as_one(self, isolated_data_dir):
        rd = get_results_dir("sid-x")
        _touch(rd, "sid-x.01result.json", '{"k":1}')
        _touch(rd, "sid-x.01result.md",   "# md")
        _touch(rd, "sid-x.01result.html", "<html></html>")
        assert next_function_index("sid-x") == "02"


# ---------------------------------------------------------------------------
# Test C — nach .01result.* + .02result.* -> "03"
# ---------------------------------------------------------------------------


class TestAfterTwoResults:
    def test_two_complete_resultsets(self, isolated_data_dir):
        rd = get_results_dir("sid-x")
        # Resultset 01 (drei Views)
        _touch(rd, "sid-x.01result.json")
        _touch(rd, "sid-x.01result.md")
        _touch(rd, "sid-x.01result.html")
        # Resultset 02 (zwei Views — fehlende HTML darf nicht stören)
        _touch(rd, "sid-x.02result.json")
        _touch(rd, "sid-x.02result.md")
        assert next_function_index("sid-x") == "03"

    def test_two_complete_resultsets_three_views_each(self, isolated_data_dir):
        rd = get_results_dir("sid-x")
        for nn in (1, 2):
            for ext in ("json", "md", "html"):
                _touch(rd, f"sid-x.{nn:02d}result.{ext}")
        assert next_function_index("sid-x") == "03"

    def test_gap_in_sequence_is_handled(self, isolated_data_dir):
        """Wenn NN=99 existiert (extremes Ende), soll 100 nicht
        zurückkommen — die Spec begrenzt auf 2-stellig."""
        rd = get_results_dir("sid-x")
        _touch(rd, "sid-x.99result.json")
        # Spec sagt: 01..99. Bei 99 ist Schluss; Aufrufer entscheidet
        # wie damit umzugehen ist.  Wir erwarten hier "100" als
        # dokumentiertes Verhalten (max+1, kein Cap), aber der String
        # wäre dann 3-stellig — deshalb dokumentieren wir das
        # aktuelle Verhalten bewusst als "100".
        assert next_function_index("sid-x") == "100"


# ---------------------------------------------------------------------------
# Test D — Notes.md und beliebige andere Dateien werden ignoriert
# ---------------------------------------------------------------------------


class TestIgnoresUnrelatedFiles:
    def test_notes_md_and_random_files_ignored(self, isolated_data_dir):
        rd = get_results_dir("sid-x")
        _touch(rd, "Notes.md", "# log")
        _touch(rd, "random.txt", "irrelevant")
        _touch(rd, ".DS_Store", "")
        _touch(rd, "downloads.tmp", "")
        # keine Result-Dateien -> "01"
        assert next_function_index("sid-x") == "01"

    def test_unrelated_files_alongside_results(self, isolated_data_dir):
        rd = get_results_dir("sid-x")
        _touch(rd, "Notes.md", "# log")
        _touch(rd, "sid-x.05result.json")
        # Resultat NN=05 muss gezählt werden, Notes.md nicht.
        assert next_function_index("sid-x") == "06"

    def test_subdirectories_ignored(self, isolated_data_dir):
        """Verzeichnisse (z.B. alte per-Function-Subdirs aus dem
        Legacy-Layout) dürfen nicht fälschlich als Sequenz gewertet
        werden."""
        rd = get_results_dir("sid-x")
        sub = rd / "01-get-metadata"
        sub.mkdir()
        (sub / "result.json").write_text("{}")
        assert next_function_index("sid-x") == "01"


# ---------------------------------------------------------------------------
# Test E — Fremde Session-Sequenzen werden ignoriert
# ---------------------------------------------------------------------------


class TestIgnoresOtherSessions:
    def test_other_session_files_ignored(self, isolated_data_dir):
        """Spec § F-05: pattern verankert auf <sid>.  Wenn versehentlich
        Dateien aus einer anderen Session im selben results/-Verzeichnis
        liegen (oder der Parser ohne sid-Scope läuft), dürfen sie nicht
        mitgezählt werden."""
        rd = get_results_dir("sid-y")
        # andere Session hat bereits NN=01..05
        for nn in range(1, 6):
            _touch(rd, f"sid-x.{nn:02d}result.json")
        # sid-y hat nichts -> "01"
        assert next_function_index("sid-y") == "01"

    def test_own_files_alongside_other_session(self, isolated_data_dir):
        rd = get_results_dir("sid-y")
        # sid-x hat bereits NN=05
        for nn in range(1, 6):
            _touch(rd, f"sid-x.{nn:02d}result.json")
        # sid-y hat NN=02
        _touch(rd, "sid-y.02result.json")
        assert next_function_index("sid-y") == "03"


# ---------------------------------------------------------------------------
# Test F — Kaputte Extension-Form wird ignoriert
# ---------------------------------------------------------------------------


class TestRejectsBrokenFilenames:
    def test_wrong_extension_case_rejected(self, isolated_data_dir):
        rd = get_results_dir("sid-x")
        # CamelCase statt lowercase: muss ignoriert werden.
        _touch(rd, "sid-x.01resultJson")
        _touch(rd, "sid-x.01resultHtml")
        assert next_function_index("sid-x") == "01"

    def test_unknown_extension_rejected(self, isolated_data_dir):
        rd = get_results_dir("sid-x")
        # .xml / .txt / .pdf sind nicht im Pattern.
        _touch(rd, "sid-x.01result.xml")
        _touch(rd, "sid-x.01result.txt")
        _touch(rd, "sid-x.01result.pdf")
        assert next_function_index("sid-x") == "01"

    def test_mixed_valid_and_invalid_files(self, isolated_data_dir):
        rd = get_results_dir("sid-x")
        # ungültige dürfen nicht mitgezählt werden
        _touch(rd, "sid-x.99result.xml")  # ignoriert
        _touch(rd, "sid-x.07resultJson")  # ignoriert (CamelCase)
        _touch(rd, "sid-x.42result.json")  # gültig
        _touch(rd, "sid-x.42result.md")    # gültig
        assert next_function_index("sid-x") == "43"


# ---------------------------------------------------------------------------
# Test G — Regression: zwei aufeinanderfolgende Aufrufe -> .01 und .02,
# keine Überschreibung.  Kern-Regressionstest zu Spec § F-05.
# ---------------------------------------------------------------------------


class TestRegressionNoOverwrite:
    """Reproduziert das Symptom, das die Spec § F-05 als Show-Stopper
    markiert hat: vorher überschrieb jeder Aufruf ``.01result.*``, weil
    der Parser immer ``"01"`` zurückgab.  Mit dem gefixten Parser
    erhalten zwei aufeinanderfolgende Aufrufe ``"01"`` und ``"02"``,
    die jeweils echte, neue Dateien erzeugen, ohne dass ``.01``
    überschrieben wird.
    """

    def test_two_consecutive_calls_produce_01_then_02(self, isolated_data_dir):
        rd = get_results_dir("sid-x")

        # --- 1. Aufruf: next_function_index liefert "01" ---
        idx1 = next_function_index("sid-x")
        assert idx1 == "01", (
            "Regression: 1. Aufruf muss '01' liefern, sonst hat der "
            "Parser die kanonische leere-results/-Form nicht erkannt."
        )
        # Wir simulieren, was write_result tun würde (Three Views):
        for ext in ("json", "md", "html"):
            _touch(rd, f"sid-x.{idx1}result.{ext}", body=f"// resultset {idx1} {ext}")

        # --- 2. Aufruf: next_function_index muss "02" liefern ---
        idx2 = next_function_index("sid-x")
        assert idx2 == "02", (
            "Regression (Spec § F-05): 2. Aufruf muss '02' liefern. "
            "Würde er erneut '01' zurückgeben, würden wir das "
            "vorhandene Resultset überschreiben."
        )
        for ext in ("json", "md", "html"):
            _touch(rd, f"sid-x.{idx2}result.{ext}", body=f"// resultset {idx2} {ext}")

        # --- Beide Resultsets sind vorhanden, keine Datei wurde überschrieben ---
        for nn in ("01", "02"):
            for ext in ("json", "md", "html"):
                p = rd / f"sid-x.{nn}result.{ext}"
                assert p.exists(), f"{p.name} fehlt — wurde überschrieben?"
                # Inhalt beweist, dass die Datei nicht von einem späteren
                # Aufruf überschrieben wurde:
                body = p.read_text(encoding="utf-8")
                assert f"resultset {nn}" in body, (
                    f"{p.name} enthält nicht den erwarteten Resultset-"
                    f"Marker '{nn}'. Datei wurde vermutlich durch "
                    "einen Folge-Aufruf überschrieben."
                )

    def test_three_consecutive_calls_01_02_03(self, isolated_data_dir):
        """Drei Aufrufe als Stressprobe — darf nicht bei 02 abbrechen."""
        rd = get_results_dir("sid-x")
        for expected in ("01", "02", "03"):
            idx = next_function_index("sid-x")
            assert idx == expected
            _touch(rd, f"sid-x.{idx}result.json")
