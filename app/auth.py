"""API-Key Authentifizierung — einheitlich für HTTP, ZMQ, MCP stdio."""
from __future__ import annotations

import hmac
from typing import Any

from fastapi import Header, HTTPException, status

from app.config import settings
from app.exceptions import AuthError


def _check_key(provided: str | None) -> None:
    """Vergleicht provided mit settings.api_key via constant-time."""
    expected = settings.api_key
    if not expected:
        return  # Dev-Mode: kein Key = offen
    if not provided:
        raise AuthError("Missing API key")
    if not hmac.compare_digest(str(provided), str(expected)):
        raise AuthError("Invalid API key")


def verify_http_key(x_api_key: str | None = Header(default=None)) -> None:
    """FastAPI-Dependency für HTTP."""
    try:
        _check_key(x_api_key)
    except AuthError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e))


def verify_zmq_key(args: dict[str, Any]) -> None:
    """Prüft api_key in ZMQ-/MCP-Arguments."""
    _check_key(args.get("api_key"))


def require_auth_for_action(action: str) -> bool:
    """Bestimmt, ob eine Aktion Auth benötigt."""
    public = {"ping", "get_manifest", "health", "status", "tools/list"}
    return action not in public
