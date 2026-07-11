# ARCHITECTURE.md — ME4-YouTube

> Detaillierte Architektur-Dokumentation

---

## 1. Design-Prinzipien

1. **Schnittstellen-Konformität**: MCP + ZMQ + WSSP-15 + Framie (per Standard verbindlich)
2. **Parallele Verarbeitung**: Eingebauter Loadbalancer mit Worker-Pool
3. **Direkter Status-Stream**: Framie-UI läuft im Service, nicht extern
4. **Trennung**: HTTP / ZMQ / Worker / Loadbalancer sind unabhängige Layer
5. **Pydantic überall**: Input-Validierung als erste Verteidigungslinie
6. **Strukturiertes Logging**: JSON-Format, ELK/Loki-kompatibel
7. **Graceful Shutdown**: Alle Layer fahren sauber herunter

---

## 2. Datenfluss

### Verarbeitung einer YouTube-URL

```
Client (Browser / Agent / curl)
    │
    │  POST /api/process   ─────┐
    │  ZMQ tools/call       ────┤
    │  MCP stdio            ────┤
    ▼                           │
HTTP / ZMQ / stdio             │
    │                           │
    ▼                           │
ZMQService._tools_call         │
    │                           │
    ├── process: WorkerPool.select_worker()
    │       │
    │       ▼
    │   Worker (HTTP :8771+)
    │       │
    │       ▼
    │   Orchestrator.process(request)
    │       │
    │       ├── 1. extract_video_id(url)
    │       ├── 2. get_video_metadata(vid)        ─► yt-dlp
    │       ├── 3. get_transcript(vid, [lang])     ─► youtube-transcript-api
    │       ├── 4. download_video(vid)             ─► yt-dlp (optional)
    │       └── 5. get_video_comments(vid, n)      ─► yt-dlp
    │       │
    │       ▼
    │   ProcessResponse
    │       │
    │       ├── status_tracker.update()           ─► SSE-Stream
    │       └── status_tracker.finish()           ─► Framie-UI
    │
    ▼
Response (JSON)
```

### Status-Stream (Framie)

```
Orchestrator
    │
    ▼
StatusTracker.update(job_id, state, step, progress)
    │
    ├── _jobs[job_id] = job
    └── _publish(envelope, event="job.updated")
            │
            ▼
        Subscribers (Queues)
            │
            ├── HTTP SSE: /api/framie/stream
            │       │
            │       ▼
            │   Browser: <li>... mit Progress-Bar
            │
            └── Andere Konsumenten (z. B. ZMQ-SSE-Bridge)
```

---

## 3. Sicherheit

### Auth-Layer

```
HTTP:  X-API-Key Header → app/auth.py:verify_http_key
ZMQ:   arguments.api_key → app/auth.py:verify_zmq_key
MCP:   arguments.api_key → app/auth.py:verify_zmq_key
```

**HMAC-Compare** (`hmac.compare_digest`) verhindert Timing-Attacks.

**Dev-Mode**: Wenn `API_KEY=""` in `.env`, ist Auth deaktiviert.
**Produktion**: `API_KEY=<starkes-passwort>` setzen.

### Input-Validierung

Alle User-Inputs werden durch Pydantic-Modelle validiert:

```python
class ProcessRequest(BaseModel):
    url: str = Field(..., min_length=1, max_length=500)
    max_comments: int = Field(default=100, ge=0, le=5000)
    # ... etc.

    @field_validator("url")
    @classmethod
    def _check_url(cls, v: str) -> str:
        if "youtube.com" not in v and "youtu.be" not in v:
            raise InvalidURLError(...)
        return v
```

### yt-dlp-Sicherheit

- `skip_download=True` bei Metadaten/Kommentaren
- `noplaylist=True` (kein versehentlicher Playlist-Download)
- `quiet=True, no_warnings=True` (kein Output-Leak)
- URL-Sanitisierung (nur YouTube-Patterns erlaubt)
- `max_download_size_mb` verhindert Disk-Fill

---

## 4. Performance

### Caching-Strategien

| Was | Wo | TTL |
|---|---|---|
| YouTube-Transcripts | youtube-transcript-api (intern) | session |
| Worker-Selektion | WorkerPool (Memory) | runtime |
| Status-Jobs | StatusTracker (Memory) | 200 (history) |

### Parallelisierung

- **N Worker-Instanzen** (default: 2, konfigurierbar bis 20)
- Jeder Worker hat eigenen HTTP-Server + Orchestrator
- Load-Balancer-Strategien: `least_loaded` (default), `round_robin`, `random`
- Heartbeat-Überwachung: Worker > 30s ohne Heartbeat = down

### Async-Stack

- `asyncio` für gesamten Service
- `httpx` (async) für SM-Producer und Worker→Loadbalancer
- `uvicorn` async-Server für HTTP
- `pyzmq` async Context für ZMQ
- `yt-dlp` blockierend → wird via `loop.run_in_executor` in Thread ausgelagert

---

## 5. Fehlerbehandlung

### Exception-Hierarchie

```
YouTubeServiceError (Basis)
├── InvalidURLError
├── VideoNotFoundError
├── TranscriptUnavailableError
├── CommentsUnavailableError
├── DownloadError
├── WorkerUnavailableError
├── AuthError
└── ConfigurationError
```

### Logging-Strategie

- **JSON-Format** in Datei (Production)
- **Text-Format** in Console (Development)
- **Strukturierte Extras** für `job_id`, `worker_id`, etc.
- **Nie Tokens/Passwörter loggen**

### Graceful Shutdown

Reihenfolge:
1. HTTP-Server: keine neuen Requests
2. ZMQ-Main: keine neuen Requests
3. ZMQ-Loadbalancer: stoppen
4. Worker-Pool: alle Worker stoppen
5. asyncio-Loop beenden

---

## 6. Tests

| Test | Datei | Was |
|---|---|---|
| URL-Parsing | test_extractor.py | 8 Tests (verschiedene URL-Formate) |
| Pydantic-Validierung | test_models.py | 7 Tests (min, max, invalid) |
| Auth | test_auth.py | 6 Tests (public, protected, dev-mode) |
| StatusTracker | test_status_tracker.py | 6 Tests (create, update, finish, SSE) |
| WorkerPool | test_loadbalancer.py | 4 Tests (Strategien, status) |
| Settings | test_config.py | 7 Tests (CORS-Parsing, Bounds) |
| HTTP API | test_http_api.py | 5 Tests (root, health, manifest, status) |
| ZMQ Service | test_zmq_service.py | 5 Tests (tools, init, auth) |

**Total: 48 Tests, alle ohne Netzwerk-Calls** (außer bei tatsächlicher
YouTube-Extraktion — dort mocken wir).

---

## 7. Deployment-Optionen

### Standalone (Dev)

```bash
python main.py
```

### Docker

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY . .
RUN pip install --no-cache-dir -r requirements.txt
EXPOSE 8770 5570 5571
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
  CMD curl -f http://localhost:8770/api/health || exit 1
CMD ["python", "main.py", "--no-browser"]
```

### Docker-Compose

```yaml
services:
  me4-youtube:
    build: .
    ports:
      - "8770:8770"
      - "5570:5570"
      - "5571:5571"
    environment:
      - API_KEY=${API_KEY}
      - SM_PRODUCER_URL=http://smproducer:3001
    restart: unless-stopped
```

### Systemd

Siehe [`SERVICE_START.md` § 10 Deployment](SERVICE_START.md#10-deployment).

---

## 8. Monitoring

| Was | Wie | Wann |
|---|---|---|
| Service-Health | `GET /api/health` | bei Bedarf |
| Worker-Health | Heartbeat (Memory) | alle 10s intern |
| Job-Status | `GET /api/status` | live |
| SSE-Stream | `GET /api/framie/stream` | live |
| Log-Datei | `service.log` (JSON) | dauerhaft |

---

## 9. Erweiterungsmöglichkeiten

- **GPU-Beschleunigung** für Transcripts (Whisper lokal)
- **Subtitles-Generierung** (SRT/VTT-Export)
- **Channel-Monitoring** (regelmäßig neue Videos pollen)
- **LLM-Integration** (Transkript zusammenfassen, Insights)
- **PostgreSQL-Backend** (für Job-History)
- **Distributed Workers** (Worker auf anderen Maschinen)
