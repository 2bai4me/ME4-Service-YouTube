"""Service-Exceptions für ME4-YouTube."""
from __future__ import annotations


class YouTubeServiceError(Exception):
    """Basis-Exception."""


class InvalidURLError(YouTubeServiceError):
    """YouTube-URL konnte nicht geparst werden."""


class VideoNotFoundError(YouTubeServiceError):
    """Video existiert nicht oder ist privat."""


class TranscriptUnavailableError(YouTubeServiceError):
    """Kein Transkript verfügbar."""


class CommentsUnavailableError(YouTubeServiceError):
    """Kommentare konnten nicht geladen werden."""


class DownloadError(YouTubeServiceError):
    """Download fehlgeschlagen."""


class WorkerUnavailableError(YouTubeServiceError):
    """Kein Worker im Pool verfügbar."""


class AuthError(YouTubeServiceError):
    """Authentifizierung fehlgeschlagen."""


class ConfigurationError(YouTubeServiceError):
    """Konfigurationsfehler."""
