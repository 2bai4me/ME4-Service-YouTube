"""Tests für Pydantic-Modelle."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.exceptions import InvalidURLError
from app.models import ProcessRequest


class TestProcessRequest:
    """Tests für ProcessRequest — Input-Validierung."""

    def test_minimal_valid(self):
        req = ProcessRequest(url="https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        assert req.url == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        assert req.download is False
        assert req.include_description is True
        assert req.language == "de"

    def test_full_valid(self):
        req = ProcessRequest(
            url="https://youtu.be/dQw4w9WgXcQ",
            download=True,
            audio_only=True,
            include_description=True,
            include_transcript=True,
            include_comments=True,
            language="en",
            max_comments=200,
        )
        assert req.download is True
        assert req.audio_only is True
        assert req.max_comments == 200

    def test_short_url(self):
        req = ProcessRequest(url="https://youtu.be/dQw4w9WgXcQ")
        assert "youtu.be" in req.url

    def test_invalid_url_raises(self):
        with pytest.raises(InvalidURLError):
            ProcessRequest(url="https://example.com/foo")

    def test_max_comments_bounds(self):
        with pytest.raises(ValidationError):
            ProcessRequest(url="https://youtu.be/dQw4w9WgXcQ", max_comments=99999)

    def test_url_too_long(self):
        with pytest.raises(ValidationError):
            ProcessRequest(url="x" * 600)

    def test_empty_url_raises(self):
        with pytest.raises(ValidationError):
            ProcessRequest(url="")
