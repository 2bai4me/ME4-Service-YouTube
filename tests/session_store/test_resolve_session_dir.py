"""Tests fuer ``app.session_store.resolve_session_dir`` (Spec AD-8 / Phase 4).

``resolve_session_dir`` ist der Backward-Compat-Read-Pfad: er akzeptiert
fuer mindestens eine Minor-Release BEIDE Layouts (singular
``data/session/`` und legacy plural ``data/sessions/``), gibt aber
klar definiert zurueck, in welcher Reihenfolge er sucht.

Aufloesungs-Reihenfolge (siehe ``app/session_store.py``):
  1. ``<DATA_DIR>/session/<safe_id>/``  wenn existent (post-Migration)
  2. ``<DATA_DIR>/sessions/<safe_id>/`` wenn existent (pre-v1.1.0)
  3. Sonst: canonical singular erzeugen, legacy NICHT anlegen

Write-Pfade (z.B. ``write_result``) muessen weiterhin
``get_session_dir`` direkt nutzen, damit neue Daten immer im
kanonischen singular-Layout landen.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app import session_store
from app.session_store import resolve_session_dir


@pytest.fixture
def isolated_data_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Setze ``settings.data_dir`` auf ``tmp_path`` fuer die Test-Sandbox."""
    session_store.settings.data_dir = str(tmp_path)
    return tmp_path


class TestResolveCanonicalOnly:
    """Nur das kanonische singular-Layout existiert."""

    def test_returns_canonical_when_canonical_exists(
        self, isolated_data_dir, tmp_path: Path
    ):
        canonical = tmp_path / "session" / "sid-a"
        canonical.mkdir(parents=True)
        out = resolve_session_dir("sid-a")
        assert out == canonical

    def test_does_not_create_legacy_when_canonical_exists(
        self, isolated_data_dir, tmp_path: Path
    ):
        """Read-Pfad darf ``data/sessions/`` nicht anlegen, wenn
        ``data/session/`` schon da ist."""
        canonical = tmp_path / "session" / "sid-b"
        canonical.mkdir(parents=True)
        resolve_session_dir("sid-b")
        assert not (tmp_path / "sessions").exists(), (
            "resolve_session_dir hat unerwartet legacy data/sessions/ "
            "angelegt, obwohl data/session/ schon existiert"
        )


class TestResolveLegacyOnly:
    """Nur das legacy plural-Layout existiert (pre-v1.1.0-Zustand)."""

    def test_returns_legacy_when_only_legacy_exists(
        self, isolated_data_dir, tmp_path: Path
    ):
        legacy = tmp_path / "sessions" / "sid-c"
        legacy.mkdir(parents=True)
        out = resolve_session_dir("sid-c")
        assert out == legacy

    def test_legacy_path_returned_not_canonical_when_only_legacy(
        self, isolated_data_dir, tmp_path: Path
    ):
        """Wenn nur legacy existiert, MUSS der legacy-Pfad zurueckgegeben
        werden — kein stiller Wechsel auf canonical, sonst wuerden
        pre-1.1.0-Reads ins Leere laufen."""
        legacy = tmp_path / "sessions" / "sid-d"
        legacy.mkdir(parents=True)
        out = resolve_session_dir("sid-d")
        assert "sessions" in out.parts, (
            f"resolve_session_dir liefert nicht das legacy-Layout: {out}"
        )
        assert "session" not in out.parts or out == legacy, (
            f"Unerwarteter Mix: {out}"
        )


class TestResolveNeither:
    """Weder canonical noch legacy existieren."""

    def test_creates_canonical_when_neither_exists(
        self, isolated_data_dir, tmp_path: Path
    ):
        """Wenn nichts existiert, wird canonical (singular) angelegt —
        NIEMALS legacy (plural)."""
        out = resolve_session_dir("sid-e")
        assert out == (tmp_path / "session" / "sid-e")
        assert out.exists()
        assert out.is_dir()

    def test_does_not_create_legacy_when_creating_canonical(
        self, isolated_data_dir, tmp_path: Path
    ):
        resolve_session_dir("sid-f")
        assert not (tmp_path / "sessions").exists(), (
            "resolve_session_dir hat legacy data/sessions/ angelegt — "
            "Write-Pfad darf nur canonical anlegen."
        )


class TestResolveCanonicalPreferred:
    """Beide Layouts existieren (theoretischer Misch-Zustand) → canonical wins."""

    def test_canonical_wins_when_both_exist(
        self, isolated_data_dir, tmp_path: Path
    ):
        canonical = tmp_path / "session" / "sid-g"
        legacy = tmp_path / "sessions" / "sid-g"
        canonical.mkdir(parents=True)
        legacy.mkdir(parents=True)
        out = resolve_session_dir("sid-g")
        assert out == canonical, (
            f"Bei beiden Layouts MUSS canonical priorisiert werden: {out}"
        )
