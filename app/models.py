"""Pydantic-Modelle für Request/Response."""
from __future__ import annotations

from typing import Any, List, Optional

from pydantic import BaseModel, Field, field_validator

from app.exceptions import InvalidURLError


class ProcessRequest(BaseModel):
    """Universeller Verarbeitungs-Request."""
    url: str = Field(..., min_length=1, max_length=500)
    download: bool = False
    download_format: str = Field(default="bestvideo[ext=mp4]+bestaudio[ext=m4a]/best")
    audio_only: bool = False
    include_description: bool = True
    include_transcript: bool = True
    include_comments: bool = True
    language: str = "de"
    max_comments: int = Field(default=100, ge=0, le=5000)
    metadata_extra: dict[str, Any] = Field(default_factory=dict)

    @field_validator("url")
    @classmethod
    def _check_url(cls, v: str) -> str:
        if "youtube.com" not in v and "youtu.be" not in v:
            raise InvalidURLError(f"not a YouTube URL: {v}")
        return v


class ProcessResponse(BaseModel):
    """Universelle Verarbeitungs-Response."""
    status: str = "ok"
    video_id: str
    url: str
    description: Optional[str] = None
    metadata: Optional[dict[str, Any]] = None
    transcript: Optional[dict[str, Any]] = None
    comments: Optional[List[dict[str, Any]]] = None
    download_path: Optional[str] = None
    error: Optional[str] = None
    duration_sec: float = 0.0
    worker_id: Optional[str] = None


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str
    uptime_sec: float
    workers_active: int
    workers_total: int
    loadbalancer: Optional[dict[str, Any]] = None


class WorkerInfo(BaseModel):
    worker_id: str
    host: str
    port: int
    status: str  # idle | busy | down
    current_load: int
    total_processed: int
    last_heartbeat: float


class SMProduceRequest(BaseModel):
    video_url: str
    transcript: Optional[str] = None
    language: str = "de"
    workflow: str = "default"
    metadata: Optional[dict[str, Any]] = None
