"""Tests fuer ``app.session_store.get_session_dir`` (Spec AD-8 / Phase 4).

Spec-Zitat (Phase 4, ``.spec/offen/me4-youtube-spec/architecture.md``):

  ``<DATA_DIR>/session/<safe_sid>/``  (singular)

Diese Tests verriegeln genau diese Form: ``get_session_dir`` MUSS
``<DATA_DIR>/session/<safe_sid>/`` liefern, NICHT
``<DATA_DIR>/sessions/<safe_sid>/`` (das waere das alte pre-1.1.0
Layout und produziert die ME4-UI-Validator Stage-3-Warnung).

Idempotenz / Side-effect-Garantien:
  * Mehrere Calls liefern denselben Pfad.
  * Der Pfad wird angelegt, falls er fehlt.
  * ``safe_id`` ist der schon vorhandene Sanitisations-Output
    (alnum + ``-`` + ``_``); ein leerer / unsicherer ``session_id``
    wird zu ``"unknown"``.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app import session_store
from app.session_store import get_session_dir


@pytest.fixture
def isolated_data_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Setze ``settings.data_dir`` auf ``tmp_path`` fuer die Test-Sandbox."""
    session_store.settings.data_dir = str(tmp_path)
    return tmp_path


class TestSingularSessionDir:
    """Vertrag: ``get_session_dir`` liefert das singular ``data/session/``."""

    def test_returns_singular_data_session_dir(
        self, isolated_data_dir, tmp_path: Path
    ):
        """``get_session_dir("sid-x")`` -> ``tmp_path / "session" / "sid-x"``.

        Wichtig: NICHT ``tmp_path / "sessions" / "sid-x"`` (Plural).  Das
        waere die alte pre-1.1.0-Layout-Form, die im Spec als AD-8
        ausdruecklich als falsch markiert ist.
        """
        out = get_session_dir("sid-x")
        assert out == (tmp_path / "session" / "sid-x"), (
            f"get_session_dir liefert falsche Form: {out} "
            f"(erwartet singular data/session/sid-x)"
        )

    def test_does_not_create_or_touch_legacy_plural_dir(
        self, isolated_data_dir, tmp_path: Path
    ):
        """Der Aufruf darf ``data/sessions/`` (Plural) NICHT anlegen."""
        assert not (tmp_path / "sessions").exists(), (
            "Sanity: vor dem Test existiert data/sessions/ nicht"
        )
        get_session_dir("sid-y")
        assert not (tmp_path / "sessions").exists(), (
            "get_session_dir hat unerwartet das Plural-Layout "
            "data/sessions/ angelegt — Regression!"
        )

    def test_creates_canonical_singular_dir(
        self, isolated_data_dir, tmp_path: Path
    ):
        """Der Aufruf legt ``data/session/<sid>/`` an, falls fehlend."""
        target = tmp_path / "session" / "sid-z"
        assert not target.exists()
        out = get_session_dir("sid-z")
        assert out.exists()
        assert out.is_dir()

    def test_idempotent(self, isolated_data_dir, tmp_path: Path):
        """Zwei Calls liefern denselben Pfad (kein Drift)."""
        a = get_session_dir("sid-i")
        b = get_session_dir("sid-i")
        assert a == b
        assert a == (tmp_path / "session" / "sid-i")

    def test_sanitises_session_id(self, isolated_data_dir, tmp_path: Path):
        """Unerlaubte Zeichen werden rausgefiltert (alnum + ``-`` + ``_``)."""
        out = get_session_dir("sid with spaces & symbols!")
        # Erwartet: nur alnum + - + _
        expected = tmp_path / "session" / "sidwithspacessymbols"  # spaces + & + ! raus
        assert out == expected, (
            f"Sanitisations-Output weicht ab: {out} vs {expected}"
        )

    def test_empty_session_id_becomes_unknown(
        self, isolated_data_dir, tmp_path: Path
    ):
        """Leere / voll-unsichere IDs werden zu ``unknown``."""
        out = get_session_dir("!!!")
        assert out == (tmp_path / "session" / "unknown"), (
            f"Nicht-alnum-ID landet nicht in 'unknown': {out}"
        )
