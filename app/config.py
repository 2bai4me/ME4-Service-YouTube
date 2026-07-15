"""Konfiguration für ME4-YouTube via Pydantic-Settings (.env + ENV)."""
from __future__ import annotations

from typing import List

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Lädt alle Konfigurationen aus .env / Umgebungsvariablen."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # === Service-Identität ===
    service_id: str = "ME4-YOUTUBE"
    service_name: str = "ME4-YouTube"
    service_version: str = "1.2.001"

    # === Ports (gemäß MCP_ZMQ_STANDARD Port-Bereiche) ===
    # 0 = "any free port" (für Tests, OS weist automatisch zu)
    http_port: int = Field(default=8770, ge=0, le=65535)
    zmq_port: int = Field(default=5570, ge=0, le=65535)
    wssp15_port: int = Field(default=5690, ge=0, le=65535)
    loadbalancer_zmq_port: int = Field(default=5571, ge=0, le=65535)

    # === Lokale Daten-Verzeichnisse ===
    # Default-Wurzel für Session-Daten (Notes.md + Funktions-Ergebnisse).
    # Plattform-portabel; per .env / Umgebungsvariable überschreibbar:
    #   DATA_DIR=./data
    data_dir: str = Field(default="./data")

    # === Pfad-Translation (WSL/Linux-Frontend -> Windows-Browser) ===
    # Wenn True, werden Pfade die mit /mnt/<drive>/ beginnen in
    # Windows-Pfade <drive>:\ umgeschrieben (fuer UI im Windows-Browser
    # bei WSL-Backend).  Default: False (Linux-natives Pfadformat).
    # Ueberschreibbar per Env-Variable WINDOWS_PATH_TRANSLATION=true oder
    # via .env.  Siehe ``app/path_utils.to_platform_path``.
    windows_path_translation: bool = Field(
        default=False,
        description=(
            "Wenn True, werden Pfade die mit /mnt/<drive>/ beginnen in "
            "Windows-Pfade <DRIVE>:\\\\ umgeschrieben (fuer UI im "
            "Windows-Browser bei WSL-Backend). Default: False (Linux-natives "
            "Pfadformat)."
        ),
    )

    # === Auth ===
    api_key: str = Field(default="", description="API-Key, falls leer = offen (nur dev)")

    # === Worker-Pool / Loadbalancer ===
    worker_count: int = Field(default=2, ge=1, le=20, description="Anzahl paralleler Worker-Instanzen")
    worker_base_port: int = Field(default=8771, ge=1024, le=65500)
    auto_start_workers: bool = Field(default=True, description="Worker beim Start automatisch hochfahren")
    loadbalancer_strategy: str = Field(default="least_loaded", description="round_robin | least_loaded | random")

    # === CORS / Host ===
    cors_origins: List[str] = Field(default_factory=lambda: ["http://localhost", "http://127.0.0.1"])
    host: str = "0.0.0.0"

    # === Download-Pfade ===
    # Basis-Verzeichnis für Video-/Audio-Downloads. Plattform-portabel;
    # per .env / Umgebungsvariable überschreibbar:
    #   DOWNLOAD_DIR=./downloads
    # Single source of truth: this declaration. (Earlier duplicate under
    # "Lokale Daten-Verzeichnisse" was silently shadowed by pydantic and
    # removed in commit fix(config): dedupe download_dir + portable data_dir.)
    download_dir: str = Field(default="./downloads", description="Basis-Verzeichnis für Downloads")
    max_download_size_mb: int = Field(default=500, ge=1, le=10240)
    download_timeout_sec: int = Field(default=300, ge=10, le=3600)

    # === Logging ===
    log_level: str = "INFO"
    log_file: str = "service.log"

    # === SM-Producer Anbindung ===
    sm_producer_url: str = "http://localhost:3001"
    sm_producer_api_key: str = ""
    sm_producer_enabled: bool = True

    # === Limits ===
    max_comments: int = Field(default=500, ge=1, le=5000)
    request_timeout_sec: int = Field(default=120, ge=5, le=600)

    @field_validator("loadbalancer_strategy")
    @classmethod
    def _validate_strategy(cls, v: str) -> str:
        allowed = {"round_robin", "least_loaded", "random"}
        if v not in allowed:
            raise ValueError(f"strategy must be one of {allowed}")
        return v

    @field_validator("log_level")
    @classmethod
    def _validate_log_level(cls, v: str) -> str:
        v = v.upper()
        if v not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError(f"invalid log level: {v}")
        return v

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _parse_cors(cls, v):
        """Akzeptiert JSON-Array, Komma-Liste oder Einzelwert."""
        if isinstance(v, list):
            return v
        if isinstance(v, str) and v.strip():
            s = v.strip()
            if s.startswith("["):
                import json
                return json.loads(s)
            return [x.strip() for x in s.split(",") if x.strip()]
        return ["http://localhost"]


settings = Settings()
