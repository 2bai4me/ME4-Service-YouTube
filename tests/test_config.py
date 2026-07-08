"""Tests für Konfiguration."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.config import Settings


class TestConfig:
    """Tests für Settings-Validierung."""

    def test_defaults(self):
        s = Settings(api_key="test")
        assert s.service_id == "ME4-YOUTUBE"
        assert s.service_version == "1.0.0"
        assert s.worker_count >= 1
        assert s.worker_count <= 20

    def test_cors_parse_string(self):
        s = Settings(api_key="test", cors_origins="a,b,c")
        assert s.cors_origins == ["a", "b", "c"]

    def test_cors_parse_list(self):
        s = Settings(api_key="test", cors_origins=["x", "y"])
        assert s.cors_origins == ["x", "y"]

    def test_cors_parse_json(self):
        s = Settings(api_key="test", cors_origins='["http://a","http://b"]')
        assert s.cors_origins == ["http://a", "http://b"]

    def test_invalid_strategy_raises(self):
        with pytest.raises(ValidationError):
            Settings(api_key="test", loadbalancer_strategy="invalid")

    def test_invalid_log_level_raises(self):
        with pytest.raises(ValidationError):
            Settings(api_key="test", log_level="VERBOSE")

    def test_worker_count_bounds(self):
        with pytest.raises(ValidationError):
            Settings(api_key="test", worker_count=0)
        with pytest.raises(ValidationError):
            Settings(api_key="test", worker_count=100)

    def test_port_bounds(self):
        # 0 ist OK (auto-assign für Tests)
        Settings(api_key="test", http_port=0)
        # > 65535 nicht erlaubt
        with pytest.raises(ValidationError):
            Settings(api_key="test", http_port=99999)
