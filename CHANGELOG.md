# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/de/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Planned
- `docs/INTEGRATION.md` — formaler UI↔Service-Vertrag (Pilot-Phase 5)
- Removal der deklarierten aber nicht implementierten Slot-Routen 6–9 (vgl. `FUNCTIONS.md` §8)

## [1.0.0] - 2026-07-11

### Added
- Vollständiges Service-Manifest unter `/api/manifest` mit 6 Funktionen, 10 Pipeline-Stages, 10 Button-Slots
- MCP-Server (stdio + ZMQ REQ/REP auf Port 5570) + HTTP-API (Port 8770)
- Eingebauter Loadbalancer-MCP auf Port 5571 mit Worker-Pool (default 2 Worker auf 8771+)
- Framie-UI als embedded Live-Status-Display unter `/ui/index.html`
- SSE-Stream `/api/framie/stream` (15s keepalive) für Worker-/Job-Updates
- SM-Producer-Anbindung (`POST /api/sm-produce`, konfigurierbar via `SM_PRODUCER_URL`)
- API-Key Auth (HMAC-compare, `app/auth.py`), Dev-Mode wenn `API_KEY=""`
- Compliance mit `MCP_ZMQ_STANDARD.md` (ZMQ REQ/REP JSON-RPC 2.0, `tools/list`/`tools/call`)
- Standard-Badge-Block in `README.md` (Pilot-Phase 2)
- Funktions-Katalog `FUNCTIONS.md` mit UI-Step-Flows + JSON-Request/Response-Beispielen
- 48+ Tests (pytest, keine Netzwerk-Calls außer bei echter Extraktion — dort gemockt)

### Changed
- BREAKING: Service-Manifest-Schema erweitert um `kind: "service"` und `mcp{}`-Block — UI-Bausteine MÜSSEN `kind` ignorieren können, falls nicht vorhanden (Vorwärtskompatibilität)
- BREAKING: `bodyTemplate` ist Pflicht in jedem Button-Target — UI-Bausteine dürfen leere Templates als Fehler behandeln
- Konfiguration `DOWNLOAD_DIR` und `DATA_DIR` sind jetzt relativ zum `WORKDIR` auflösbar (vorher: hart `./data`)

### Removed
- WSSP-15 Heartbeat-Feature komplett entfernt (`wssp15_port` aus Manifest, Import in `main.py`, Tests, Docs) — das `wssp15`-Paket existierte nie auf PyPI, Service lief im "degraded mode"
- Hartcodierte Worker-Heartbeat-Schwelle (30s) durch konfigurierbare `LOADBALANCER_HEARTBEAT_TIMEOUT_SEC` ersetzt

### Fixed
- `config-dedupe-and-portable-data-dir`: Doppelte `download_dir`-Definition entfernt; portable `data_dir`-Default (vgl. `c0d3401`)
- CRLF→LF Normalisierung via `.gitattributes` (54 Dateien umgeschrieben auf LF, kein semantischer Diff)

## [0.1.0] - 2026-07-08

### Added
- Initial commit: ME4-YouTube v1.0.0
- Grundgerüst: yt-dlp-basierter Video-/Audio-Download, Metadaten-Extraktion, Transkript-Service, Top-Kommentare
- FastAPI HTTP-API, pyzmq-basierter MCP-Server
- Pydantic-Modelle für Input-Validierung in `app/models.py`
- Strukturierte JSON-Logs (`app/logging_config.py`)
- Graceful Shutdown aller Layer (HTTP → ZMQ-Main → ZMQ-LB → Worker-Pool → Event-Loop)

[Unreleased]: https://github.com/2bai4me/ME4-S-youtube/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/2bai4me/ME4-S-youtube/releases/tag/v1.0.0
[0.1.0]: https://github.com/2bai4me/ME4-S-youtube/releases/tag/v0.1.0