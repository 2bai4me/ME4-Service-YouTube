r"""Phase-4b Plattform-portable Pfade + ``files[].openUrl`` Tests (Spec E-4 + YT-08).

Bezug: .spec/offen/me4-ui-service-owned-interaction-v1-audit-2026-07-12.md
       § "Anforderungsliste ME4-S-youtube" -> YT-08 + UI-04 + E-4
       (Pfad-Translation + Open-Button-faehige Felder).

Phase 4b erweitert den YT-08-Response-Contract um zwei Aspekte:

  1. **Plattform-portable Pfade**: Das Backend laeuft auf Linux/WSL,
     die UI im Windows-Browser.  Wenn der User die UI im
     Windows-Browser oeffnet, erwartet er Windows-Pfade
     (``D:\\DEV\\...``) -- nicht die rohen ``/mnt/d/...``-Strings.
     Das neue Setting ``settings.windows_path_translation`` (Env-Variable
     ``WINDOWS_PATH_TRANSLATION=true``) schaltet die Translation ein
     und greift fuer ALLE 6 Pfad-Felder im Response-Contract:
     ``dirAbsolute``, ``filesSavedTo``, ``resultsDir``, ``sessionDir``,
     ``jsonPath``, ``mdPath``, ``htmlPath``.

  2. **Open-Button-faehige ``files[]``-Felder**: Jedes File-Element
     bekommt zusaetzlich zu ``{name, size, mtimeMs}`` ein ``path``-
     Feld (gleiche Translation wie die anderen Pfad-Felder) und ein
     ``openUrl``-Feld (``file:///D:/...``-URI fuer direkten
     Browser-Open).

Diese Tests dokumentieren den Vertrag explizit und sind der
Regression-Schutz fuer kuenftige Refactorings der Pfad-Helfer.

Test-Strategie:
    * Unit-Tests auf ``to_platform_path`` mit String-Argumenten
      (filesystem-frei, isoliert).
    * Integration-Tests, die ``write_result`` + ``build_summary`` mit
      einem ``data_dir`` UNTER ``/mnt/<drive>/`` aufrufen -- nur dann
      greift die Translation tatsaechlich (per Spec: nicht-WSL-Pfade
      bleiben unveraendert).  Auf Linux-only CI ohne /mnt/-Mount wird
      ueber einen Symlink-Trick ein Pseudo-WSL-Pfad erzeugt (siehe
      ``wsl_data_dir``).
    * ``monkeypatch.setattr(settings, ...)`` und ``monkeypatch.setenv``
      werden beide genutzt; die Fixture stellt den Originalzustand in
      jedem Fall wieder her.
"""
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

import pytest

from app.config import Settings, settings
from app.path_utils import to_file_uri, to_platform_path
from app.response_contract import build_summary
from app.session_store import (
    get_results_dir,
    write_result,
)

# Marker for Windows drive-prefix translated paths (used in asserts).
_DSEP = "\\"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def isolated_data_dir(monkeypatch: pytest.MonkeyPatch):
    """Setze ``settings.data_dir`` und restore ``windows_path_translation``."""
    original = bool(settings.windows_path_translation)
    original_data_dir = settings.data_dir
    monkeypatch.setattr(settings, "windows_path_translation", original)
    yield
    settings.windows_path_translation = original
    settings.data_dir = original_data_dir


@pytest.fixture
def wsl_data_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Temporaeres Verzeichnis UNTER ``/mnt/<drive>/`` fuer echte Translation.

    Strategie:
      1. Wenn echte ``/mnt/<drive>/``-Mounts existieren (WSL): wir
         nehmen ``/mnt/d/me4-test-<pid>-<tmp_name>`` als data_dir.
      2. Sonst (Linux-only ohne /mnt-Mount): wir erzeugen einen
         Symlink ``/mnt/fake_d -> tmp_path`` und benutzen den
         Symlink-Pfad -- ``to_platform_path`` sieht dann den
         ``/mnt/fake_d/...``-Prefix und wendet Translation an.
    """
    original_data_dir = settings.data_dir
    original_flag = bool(settings.windows_path_translation)

    candidates = []
    mnt_root = Path("/mnt")
    if mnt_root.is_dir():
        # Bevorzuge /mnt/d (typischer WSL-Mount auf Dev-Maschinen); fallback
        # auf andere Drives falls /mnt/d nicht existiert.  Deterministisch
        # sortiert, damit Tests unabhaengig vom Mount-Reihenfolge identisch
        # laufen.
        drives = sorted(
            e.name for e in mnt_root.iterdir()
            if e.is_dir() and len(e.name) == 1 and e.name.isalpha()
        )
        # "d" bevorzugen, sonst erste Mount.
        preferred = "d" if "d" in drives else (drives[0] if drives else None)
        if preferred:
            target = mnt_root / preferred / ("me4-test-" + str(os.getpid()) + "-" + tmp_path.name)
            target.mkdir(parents=True, exist_ok=True)
            candidates.append(target)

    if candidates:
        wsl_root = candidates[0]
    else:
        fake_mount = mnt_root / "fake_d"
        if fake_mount.exists() or fake_mount.is_symlink():
            try:
                if fake_mount.is_symlink():
                    fake_mount.unlink()
                else:
                    shutil.rmtree(fake_mount)
            except OSError:
                pass
        fake_mount.symlink_to(tmp_path)
        wsl_root = fake_mount

    settings.data_dir = str(wsl_root)
    monkeypatch.setattr(settings, "data_dir", str(wsl_root))
    settings.windows_path_translation = False
    monkeypatch.setattr(settings, "windows_path_translation", False)

    yield wsl_root

    # Cleanup
    try:
        if wsl_root.is_symlink():
            wsl_root.unlink()
        elif wsl_root.exists():
            # nur das Test-Verzeichnis aufraeumen, NICHT /mnt/d/
            shutil.rmtree(wsl_root, ignore_errors=True)
    except OSError:
        pass
    settings.data_dir = original_data_dir
    settings.windows_path_translation = original_flag


@pytest.fixture
def with_windows_translation(wsl_data_dir):
    """Aktiviert windows_path_translation fuer den Test."""
    settings.windows_path_translation = True
    yield True
    settings.windows_path_translation = False


def _write_then_summary(sid: str, title: str, data_dir: str | None = None):
    """Hilfsfunktion: schreibt ein Resultset und baut den Summary.

    Wenn ``data_dir`` gegeben ist, wird ``settings.data_dir`` temporaer
    umgesetzt (fuer die POSIX-Form-Tests, wo ``/tmp`` reicht).
    """
    prev = None
    if data_dir is not None:
        prev = settings.data_dir
        settings.data_dir = data_dir
    try:
        write_result(
            sid, "get-metadata",
            {"success": True, "title": title},
            request={"sessionId": sid, "url": "https://x"},
        )
        s = build_summary(
            "get-metadata",
            {"jsonPath": str(get_results_dir(sid) / (sid + ".01result.json"))},
            session_id=sid,
        )
    finally:
        if prev is not None:
            settings.data_dir = prev
    return s


# ---------------------------------------------------------------------------
# 1) Pfad-Translation (Linux/WSL -> Windows-kompatibel)
# ---------------------------------------------------------------------------


class TestWindowsPathTranslation:
    """Spec E-4: ``to_platform_path()`` uebersetzt ``/mnt/<drive>/...``
    in Windows-Form, sobald das Setting aktiv ist."""

    def test_translation_disabled_linux_path_unchanged(self, isolated_data_dir):
        """Default (Setting aus): ``/mnt/d/...`` bleibt POSIX-Form."""
        out = to_platform_path("/mnt/d/DEV/foo/x.json")
        assert out == "/mnt/d/DEV/foo/x.json", (
            "Default-Verhalten sollte POSIX sein, bekam: " + repr(out)
        )

    def test_translation_enabled_wsl_to_windows(self, with_windows_translation):
        """Setting an: ``/mnt/d/...`` wird zu ``D:\\DEV\\...``."""
        out = to_platform_path("/mnt/d/DEV/foo/x.json")
        assert out == "D:" + _DSEP + "DEV" + _DSEP + "foo" + _DSEP + "x.json", (
            "WSL->Windows-Translation fehlerhaft: " + repr(out)
        )
        assert _DSEP in out, "Keine Backslashes: " + repr(out)
        assert not out.startswith("/mnt/"), (
            "Linux-Prefix nicht entfernt: " + repr(out)
        )

    def test_translation_handles_nested_subdirs(self, with_windows_translation):
        """Tiefe Subdirs werden vollstaendig uebersetzt, jeder ``/`` -> ``\\``."""
        out = to_platform_path(
            "/mnt/d/DEV/wt-me4-yt-paths-open/data/session/"
            "abc-123/results/abc-123.05result.html"
        )
        expected = (
            "D:" + _DSEP + "DEV" + _DSEP + "wt-me4-yt-paths-open" + _DSEP
            + "data" + _DSEP + "session" + _DSEP + "abc-123" + _DSEP
            + "results" + _DSEP + "abc-123.05result.html"
        )
        assert out == expected, (
            "Nested-Subdir-Translation falsch: " + repr(out)
        )
        assert out.startswith("D:" + _DSEP)
        assert out.count(_DSEP) == 7, (
            "Erwartete 7 Backslashes, bekam " + str(out.count(_DSEP))
            + ": " + repr(out)
        )

    def test_translation_ignores_non_wsl_paths(self, with_windows_translation):
        """Setting an, aber Pfad ist NICHT ``/mnt/<drive>/`` -> bleibt POSIX."""
        out_tmp = to_platform_path("/tmp/foo/results/x.json")  # noqa: S108
        assert out_tmp == "/tmp/foo/results/x.json", (  # noqa: S108
            "non-WSL-Pfad sollte NICHT uebersetzt werden: " + repr(out_tmp)
        )
        out_home = to_platform_path("/home/user/me4-data/x.json")
        assert out_home == "/home/user/me4-data/x.json", (
            "/home sollte NICHT uebersetzt werden: " + repr(out_home)
        )
        out_mnt_root = to_platform_path("/mnt/shared/x.json")
        assert out_mnt_root == "/mnt/shared/x.json", (
            "/mnt/shared (ohne drive-letter) sollte unveraendert bleiben: "
            + repr(out_mnt_root)
        )

    def test_translation_via_env_var(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        """Setting ist per Env-Variable ``WINDOWS_PATH_TRANSLATION=true`` aktivierbar."""
        monkeypatch.setenv("WINDOWS_PATH_TRANSLATION", "true")
        monkeypatch.setenv("DATA_DIR", str(tmp_path))
        s = Settings(api_key="test", data_dir=str(tmp_path))
        assert s.windows_path_translation is True, (
            "Env-Variable WINDOWS_PATH_TRANSLATION=true wurde nicht "
            "uebernommen: " + repr(s.windows_path_translation)
        )

    def test_explicit_windows_true_overrides_setting(
        self, isolated_data_dir, with_windows_translation
    ):
        """``windows=True``-Override funktioniert auch ohne/mit Setting."""
        out = to_platform_path("/mnt/c/Users/x/y.json", windows=True)
        assert out == "C:" + _DSEP + "Users" + _DSEP + "x" + _DSEP + "y.json"
        out2 = to_platform_path("/mnt/c/Users/x/y.json", windows=False)
        assert out2 == "/mnt/c/Users/x/y.json"


# ---------------------------------------------------------------------------
# 2) files[] Open-Button-Felder (path + openUrl)
# ---------------------------------------------------------------------------


class TestFilesListOpenUrl:
    """Spec E-4 + UI-04: ``files[]``-Elemente bekommen ein ``path``-
    und ein ``openUrl``-Feld."""

    def test_files_have_path_field(self, isolated_data_dir):
        """Jeder files[]-Eintrag enthaelt ein ``path``-Feld."""
        with tempfile.TemporaryDirectory() as td:
            s = _write_then_summary("yt08b-path", "Path", data_dir=td)
        assert s["files"], "files[] darf nicht leer sein"
        for f in s["files"]:
            fpath = f["path"]
            assert "path" in f, "path-Feld fehlt in files[]: " + repr(f)
            assert isinstance(fpath, str), "path ist kein str: " + repr(fpath)
            assert fpath, "path ist leer: " + repr(fpath)

    def test_files_have_file_uri_open_url(self, isolated_data_dir):
        """Jeder files[]-Eintrag hat ein ``openUrl``-Feld der Form ``file:///...``."""
        with tempfile.TemporaryDirectory() as td:
            s = _write_then_summary("yt08b-openurl", "OpenUrl", data_dir=td)
        assert s["files"]
        for f in s["files"]:
            fpath = f["path"]
            fopen = f["openUrl"]
            assert "openUrl" in f, "openUrl-Feld fehlt: " + repr(f)
            assert isinstance(fopen, str), "openUrl ist kein str: " + repr(fopen)
            assert fopen.startswith("file://"), (
                "openUrl ist kein file://-URI: " + repr(fopen)
            )
            assert fopen.startswith("file:///"), (
                "openUrl muss drei Slashes haben (absolute Pfade): "
                + repr(fopen)
            )
            expected_uri = to_file_uri(fpath)
            assert fopen == expected_uri, (
                "openUrl weicht von to_file_uri(path) ab: "
                + repr(fopen) + " vs " + repr(expected_uri)
            )

    def test_files_path_uses_same_translation_as_directory(
        self, with_windows_translation
    ):
        """Translation AN: ``dirAbsolute`` UND ``files[].path`` zeigen auf
        Windows-Pfade -- konsistent."""
        s = _write_then_summary("yt08b-translate", "Translate")
        sdir = s["dirAbsolute"]
        assert sdir.startswith("D:" + _DSEP), (
            "dirAbsolute ist nicht in Windows-Form: " + repr(sdir)
        )
        for f in s["files"]:
            fpath = f["path"]
            fopen = f["openUrl"]
            assert fpath.startswith("D:" + _DSEP), (
                "files[].path weicht von Windows-Form ab: " + repr(fpath)
            )
            assert _DSEP in fpath, (
                "files[].path hat keine Backslashes: " + repr(fpath)
            )
            assert fopen.startswith("file:///D:/"), (
                "openUrl nicht in Windows-Form: " + repr(fopen)
            )

    def test_files_path_posix_when_translation_off(self, isolated_data_dir):
        """Translation AUS: ``files[].path`` ist POSIX-Form, ``openUrl``
        ist ``file:///tmp/...``."""
        with tempfile.TemporaryDirectory() as td:
            s = _write_then_summary("yt08b-posix", "Posix", data_dir=td)
        sdir = s["dirAbsolute"]
        assert sdir.startswith("/"), (
            "dirAbsolute ist nicht POSIX: " + repr(sdir)
        )
        for f in s["files"]:
            fpath = f["path"]
            fopen = f["openUrl"]
            assert fpath.startswith("/"), (
                "files[].path nicht POSIX: " + repr(fpath)
            )
            assert _DSEP not in fpath, (
                "files[].path hat unerwartete Backslashes: " + repr(fpath)
            )
            assert fopen.startswith("file:///"), (
                "openUrl falsch: " + repr(fopen)
            )
            assert not fopen.startswith("file:///D"), (
                "openUrl hat unerwartete Windows-Form: " + repr(fopen)
            )


# ---------------------------------------------------------------------------
# 3) Top-Level-Response: alle 6 Pfad-Felder nutzen die Translation
# ---------------------------------------------------------------------------


class TestResponseContractPlatform:
    """Spec E-4 + YT-08-4..5: bei ``windows_path_translation=True`` zeigen
    ALLE 6 Pfad-Felder im Response-Contract auf Windows-Pfade."""

    def test_all_six_path_fields_use_translation_when_enabled(
        self, with_windows_translation
    ):
        """Alle 6 Top-Level-Pfad-Felder werden uebersetzt."""
        sid = "yt08b-six"
        write_result(
            sid, "get-metadata",
            {"success": True, "title": "All-Six"},
            request={"sessionId": sid, "url": "https://x"},
        )
        s = build_summary(
            "get-metadata",
            {
                "jsonPath": str(
                    get_results_dir(sid) / (sid + ".01result.json")
                ),
            },
            session_id=sid,
        )
        for key in ("dirAbsolute", "filesSavedTo", "resultsDir"):
            v = s[key]
            assert v.startswith("D:" + _DSEP), (
                key + " ist nicht in Windows-Form: " + repr(v)
            )
            assert _DSEP in v, key + " hat keine Backslashes: " + repr(v)
            assert not v.startswith("/mnt/"), (
                key + " enthaelt Linux-/mnt/-Prefix: " + repr(v)
            )
        for key in ("jsonPath", "mdPath", "htmlPath"):
            v = s[key]
            assert v is not None, key + " ist None"
            assert v.startswith("D:" + _DSEP), (
                key + " ist nicht in Windows-Form: " + repr(v)
            )
            assert _DSEP in v, key + " hat keine Backslashes: " + repr(v)
        if "sessionDir" in s:
            v = s["sessionDir"]
            assert v.startswith("D:" + _DSEP), (
                "sessionDir ist nicht in Windows-Form: " + repr(v)
            )
        for f in s["files"]:
            fpath = f["path"]
            assert fpath.startswith("D:" + _DSEP), (
                "files[].path ist nicht in Windows-Form: " + repr(fpath)
            )

    def test_all_six_path_fields_stay_posix_when_disabled(
        self, isolated_data_dir
    ):
        """Translation AUS (Default): alle Felder bleiben POSIX-Form."""
        sid = "yt08b-posix-all"
        with tempfile.TemporaryDirectory() as td:
            settings.data_dir = td
            write_result(
                sid, "get-metadata",
                {"success": True, "title": "Posix-All"},
                request={"sessionId": sid, "url": "https://x"},
            )
            s = build_summary(
                "get-metadata",
                {
                    "jsonPath": str(
                        get_results_dir(sid) / (sid + ".01result.json")
                    ),
                },
                session_id=sid,
            )
        for key in ("dirAbsolute", "filesSavedTo", "resultsDir",
                    "jsonPath", "mdPath", "htmlPath"):
            v = s[key]
            assert v.startswith("/"), (
                key + " ist nicht POSIX: " + repr(v)
            )
            assert _DSEP not in v, (
                key + " hat unerwartete Backslashes: " + repr(v)
            )
        if "sessionDir" in s:
            v = s["sessionDir"]
            assert v.startswith("/"), (
                "sessionDir nicht POSIX: " + repr(v)
            )
        for f in s["files"]:
            fpath = f["path"]
            assert fpath.startswith("/"), (
                "files[].path nicht POSIX: " + repr(fpath)
            )
