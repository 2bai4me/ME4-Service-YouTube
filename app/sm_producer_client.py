"""SM-Producer Client — Anbindung an ME4-SMproducer-3 Pipeline."""
from __future__ import annotations

from typing import Any, Optional

import httpx

from app.config import settings
from app.logging_config import get_logger

logger = get_logger(__name__)


class SMProducerClient:
    """HTTP-Client für die SM-Producer-Pipeline."""

    def __init__(self, base_url: Optional[str] = None, api_key: Optional[str] = None):
        self.base_url = (base_url or settings.sm_producer_url).rstrip("/")
        self.api_key = api_key or settings.sm_producer_api_key
        self.timeout = settings.request_timeout_sec

    def _headers(self) -> dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self.api_key:
            h["X-API-Key"] = self.api_key
        return h

    async def health(self) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=5) as c:
            r = await c.get(f"{self.base_url}/api/health", headers=self._headers())
            r.raise_for_status()
            return r.json()

    async def trigger_produce(
        self,
        video_url: str,
        transcript: str = "",
        language: str = "de",
        workflow: str = "default",
        metadata: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        payload = {
            "video_url": video_url,
            "transcript": transcript,
            "language": language,
            "workflow": workflow,
            "metadata": metadata or {},
            "source": "ME4-YouTube",
        }
        async with httpx.AsyncClient(timeout=self.timeout) as c:
            r = await c.post(
                f"{self.base_url}/api/sm-produce",
                json=payload,
                headers=self._headers(),
            )
            r.raise_for_status()
            data = r.json()
            logger.info("SM-Produce triggered: %s", data)
            return data

    async def notify(
        self,
        title: str,
        message: str,
        url: Optional[str] = None,
    ) -> dict[str, Any]:
        payload = {"title": title, "message": message, "url": url}
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.post(
                f"{self.base_url}/api/notify",
                json=payload,
                headers=self._headers(),
            )
            r.raise_for_status()
            return r.json()
