"""Tests für Authentifizierung."""
from __future__ import annotations

import pytest

from app.auth import require_auth_for_action, verify_zmq_key
from app.config import settings
from app.exceptions import AuthError


class TestAuth:
    """API-Key Authentifizierung."""

    def test_public_actions_no_auth(self):
        assert require_auth_for_action("ping") is False
        assert require_auth_for_action("get_manifest") is False
        assert require_auth_for_action("health") is False
        assert require_auth_for_action("status") is False
        assert require_auth_for_action("tools/list") is False

    def test_protected_actions_need_auth(self):
        assert require_auth_for_action("process") is True
        assert require_auth_for_action("download") is True
        assert require_auth_for_action("shutdown") is True

    def test_no_key_set_dev_mode(self, monkeypatch):
        monkeypatch.setattr(settings, "api_key", "")
        # Kein Key gesetzt = alle dürfen rein
        verify_zmq_key({"api_key": None})
        verify_zmq_key({})
        verify_zmq_key({"api_key": "anything"})

    def test_key_set_correct(self, monkeypatch):
        monkeypatch.setattr(settings, "api_key", "secret-123")
        verify_zmq_key({"api_key": "secret-123"})

    def test_key_set_wrong(self, monkeypatch):
        monkeypatch.setattr(settings, "api_key", "secret-123")
        with pytest.raises(AuthError):
            verify_zmq_key({"api_key": "wrong"})

    def test_key_set_missing(self, monkeypatch):
        monkeypatch.setattr(settings, "api_key", "secret-123")
        with pytest.raises(AuthError):
            verify_zmq_key({})
