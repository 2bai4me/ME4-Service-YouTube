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
        assert s.service_version == "1.0.7"
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


class TestConfigPaths:
    """Tests für Daten-/Download-Pfad-Auflösung.

    Fixes:
      - Bug 1: download_dir war doppelt deklariert (stillschweigend von
        pydantic dedupliziert, aber irreführend).
      - Bug 2: data_dir hatte einen Windows-Hardcode als Default.
    """

    def test_settings_loads_cleanly(self):
        """Settings muss mit den Defaults ohne Exception instanziierbar sein."""
        s = Settings(api_key="test")
        assert s is not None

    def test_download_dir_declared_once(self):
        """download_dir darf in model_fields nur einmal vorkommen (kein Shadowing)."""
        count = sum(1 for name in Settings.model_fields if name == "download_dir")
        assert count == 1, (
            f"download_dir is declared {count} times; expected exactly 1"
        )

    def test_download_dir_resolves_to_non_empty_string(self, monkeypatch):
        monkeypatch.delenv("DOWNLOAD_DIR", raising=False)
        s = Settings(api_key="test")
        assert isinstance(s.download_dir, str)
        assert s.download_dir.strip() != ""
        # Plattform-portabel: kein Windows-Pfad mit Backslash oder Laufwerksbuchstabe.
        assert "\\" not in s.download_dir
        assert ":" not in s.download_dir

    def test_download_dir_default_is_portable(self, monkeypatch):
        monkeypatch.delenv("DOWNLOAD_DIR", raising=False)
        s = Settings(api_key="test")
        assert s.download_dir == "./downloads"

    def test_download_dir_env_override(self, monkeypatch):
        monkeypatch.setenv("DOWNLOAD_DIR", "/tmp/me4-dl")  # noqa: S108
        s = Settings(api_key="test")
        assert s.download_dir == "/tmp/me4-dl"  # noqa: S108

    def test_data_dir_default_is_portable(self, monkeypatch):
        monkeypatch.delenv("DATA_DIR", raising=False)
        s = Settings(api_key="test")
        assert s.data_dir == "./data"
        assert "\\" not in s.data_dir
        assert ":" not in s.data_dir

    def test_data_dir_honours_data_dir_env(self, monkeypatch):
        monkeypatch.setenv("DATA_DIR", "/tmp/me4-data")  # noqa: S108
        s = Settings(api_key="test")
        assert s.data_dir == "/tmp/me4-data"  # noqa: S108
