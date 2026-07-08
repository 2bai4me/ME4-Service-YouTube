# SERVICE.md — ME4-YouTube

> **Service-ID:** `ME4-YOUTUBE`  
> **Version:** 1.0.0  
> **Status:** ✅ MCP + ZMQ + WSSP-15 + Framie konform  
> **Standard:** [MCP_ZMQ_STANDARD.md](./MCP_ZMQ_STANDARD.md)

---

## Übersicht

YouTube Content Extraction Service für die ME4-Suite.
Extrahiert Videos, Metadaten, Transkripte und Kommentare über
eine standardisierte MCP-Schnittstelle mit eingebautem
Load-Balancer für parallele Verarbeitung.

| Eigenschaft | Wert |
|---|---|
| **Service-ID** | `ME4-YOUTUBE` |
| **Typ** | MCP-Server (stdio + ZMQ) + HTTP + WSSP-15 + Framie |
| **HTTP-Port** | 8770 |
| **ZMQ-Port (Main)** | 5570 |
| **ZMQ-Port (Loadbalancer)** | 5571 |
| **WSSP-15 Port** | 5690 |
| **Worker-Pool** | 2 (konfigurierbar) auf 8771+ |
| **Auth** | API-Key (`X-API-Key` / `api_key`) |
| **Sprache** | Python 3.11+ |
| **Framework** | FastAPI + pyzmq |

---

## Architektur

```
┌──────────────────────────────────────────────────────────┐
│ ME4-YouTube (ME4-YOUTUBE)                                │
│                                                          │
│  ┌────────────────┐  ┌─────────────────┐                │
│  │  HTTP API      │  │  ZMQ Main       │                │
│  │  :8770         │  │  :5570          │                │
│  │  + Framie-UI   │  │  MCP REQ/REP    │                │
│  │  + SSE Stream  │  │  + UI-Manifest  │                │
│  └────────┬───────┘  └────────┬────────┘                │
│           │                   │                         │
│           └─────────┬─────────┘                         │
│                     ▼                                   │
│           ┌─────────────────────┐                       │
│           │  WorkerPool         │                       │
│           │  Strategy: least_loaded                    │
│           │  ZMQ-LB :5571       │◄──── MCP-Loadbalancer │
│           └─────────┬───────────┘                       │
│                     │                                   │
│         ┌───────────┼───────────┐                       │
│         ▼           ▼           ▼                       │
│    ┌─────────┐ ┌─────────┐ ┌─────────┐                  │
│    │worker-01│ │worker-02│ │worker-03│  (jeweils        │
│    │  :8771  │ │  :8772  │ │  :8773  │   Orchestrator)  │
│    │  HTTP   │ │  HTTP   │ │  HTTP   │                  │
│    └─────────┘ └─────────┘ └─────────┘                  │
│                                                          │
│  ┌────────────────┐  ┌─────────────────┐                │
│  │ WSSP-15 :5690  │  │  SM-Producer    │                │
│  │  Heartbeat     │  │  HTTP :3001     │                │
│  └────────────────┘  └─────────────────┘                │
│                                                          │
│  ┌────────────────────────────┐                         │
│  │  Framie-UI (static)        │                         │
│  │  /ui/index.html            │  ←── Browser beim Start │
│  │  SSE: /api/framie/stream   │                         │
│  └────────────────────────────┘                         │
└──────────────────────────────────────────────────────────┘
```

### Komponenten

| Komponente | Datei | Zweck |
|---|---|---|
| `main.py` | — | Boot-Manager, startet alle Layer in fester Reihenfolge |
| `app/config.py` | Settings via Pydantic (.env) |
| `app/auth.py` | API-Key Auth (HMAC-compare) |
| `app/exceptions.py` | 8 spezifische Exception-Typen |
| `app/logging_config.py` | Strukturiertes JSON-Logging |
| `app/extractor.py` | YouTube URL-Parser, Metadaten, Kommentare (yt-dlp) |
| `app/downloader.py` | Video/Audio-Download (yt-dlp, async) |
| `app/transcriber.py` | Transkript (youtube-transcript-api) |
| `app/orchestrator.py` | Pipeline-Koordinator pro Job |
| `app/worker.py` | Sub-Worker (eigener HTTP-Server) |
| `app/loadbalancer.py` | WorkerPool + MCP-Loadbalancer (ZMQ) |
| `app/zmq_service.py` | ZMQ REQ/REP Hauptservice |
| `app/http_api.py` | FastAPI Router + SSE-Stream |
| `app/mcp_stdio.py` | MCP-Server über stdin/stdout |
| `app/sm_producer_client.py` | SM-Producer HTTP-Client |
| `app/status_tracker.py` | In-Memory Job-Status + SSE-Bus |
| `app/models.py` | Pydantic Request/Response |
| `static/index.html` + `app.js` + `style.css` | Framie Live-Status-UI |

### Boot-Sequenz (Hauptservice)

1. **Logging** initialisieren (strukturiert, JSON)
2. **Worker-Pool** aufbauen (N Worker auf eigenen Ports)
3. **ZMQ-Loadbalancer** starten (Port 5571) — MCP-konform
4. **ZMQ-Hauptservice** starten (Port 5570) — MCP-konform
5. **WSSP-15 Heartbeat** starten (Port 5690)
6. **HTTP-API + Framie-UI** starten (Port 8770)
7. **SM-Producer** Anbindung testen (non-blocking)
8. **Framie-UI** im Browser öffnen (wenn `--no-browser` nicht gesetzt)

Siehe [SERVICE_START.md](./SERVICE_START.md) für Details.

---

## Schnittstellen

### 1. MCP / ZMQ REQ/REP (Standard)

**JSON-RPC 2.0** über TCP.

Siehe [AGENT.md](./AGENT.md) für Details.

Standard-Tools (jeder ME4-Service MUSS diese haben):
- `ping` — public
- `get_manifest` — public
- `health` — public
- `shutdown` — 🔑

Feature-Tools:
- `get_metadata` — 🔑
- `get_transcript` — 🔑
- `get_comments` — 🔑
- `download` — 🔑
- `process` — 🔑 (kombinierte Pipeline)
- `trigger_sm_produce` — 🔑
- `get_status_snapshot` — public

### 2. Loadbalancer-MCP (Port 5571)

Eigener MCP-Endpunkt mit Worker-Health-Monitoring und
Strategie-basierter Lastverteilung. Unterstützt dieselben
JSON-RPC-Tools, leitet Aufrufe aber an einen passenden
Worker weiter.

Tools:
- `ping` / `get_manifest` / `health` / `status` (public)
- `process` (🔑) — leitet an Worker weiter
- `shutdown` (🔑)

### 3. HTTP / REST (Port 8770)

Siehe [README.md](./README.md) für Endpunkte.

### 4. WSSP-15 (Port 5690)

WebSocket-Heartbeat für Cockpit / Service-Discovery.

### 5. MCP stdio (für Agenten ohne ZMQ)

`python main.py --mcp-stdio`

Liest JSON-RPC 2.0 von stdin, schreibt nach stdout.

### 6. Framie-UI (Port 8770/ui)

Embedded HTML/JS Status-Display.
Wird beim Service-Start automatisch im Browser geöffnet
(außer `--no-browser`).

**Features**:
- KPIs (Aktive Jobs, Erledigt, Fehler, Worker-Status)
- Live SSE-Stream (`/api/framie/stream`)
- Worker-Liste mit Idle/Busy/Down
- Job-Tabelle (letzte 15)
- Event-Log (Tail)

---

## Konfiguration (.env)

Siehe [`.env.example`](.env.example) für alle Optionen.

| Variable | Default | Beschreibung |
|---|---|---|
| `API_KEY` | `""` | API-Key (leer = Dev-Mode offen) |
| `HTTP_PORT` | `8770` | HTTP-API + Framie-UI |
| `ZMQ_PORT` | `5570` | ZMQ Main |
| `LOADBALANCER_ZMQ_PORT` | `5571` | ZMQ Loadbalancer |
| `WSSP15_PORT` | `5690` | WSSP-15 Heartbeat |
| `WORKER_COUNT` | `2` | Anzahl paralleler Worker |
| `WORKER_BASE_PORT` | `8771` | Basis-Port für Worker |
| `LOADBALANCER_STRATEGY` | `least_loaded` | `round_robin` / `least_loaded` / `random` |
| `DOWNLOAD_DIR` | `./downloads` | Zielordner für Downloads |
| `SM_PRODUCER_URL` | `http://localhost:3001` | SM-Producer-Pipeline |
| `SM_PRODUCER_ENABLED` | `true` | SM-Producer-Anbindung aktiv |
| `LOG_LEVEL` | `INFO` | DEBUG/INFO/WARNING/ERROR |

---

## Compliance-Checkliste (MCP+ZMQ)

- [x] ZMQ REQ/REP mit JSON-RPC 2.0 (Hauptservice + Loadbalancer)
- [x] `tools/list` und `tools/call` unterstützt
- [x] API-Key Auth (HMAC-compare, constant-time)
- [x] WSSP-15 Heartbeat aktiv
- [x] Service-ID und Version definiert (`ME4-YOUTUBE` v1.0.0)
- [x] UI-Manifest für Cockpit (`/api/manifest`)
- [x] `ping`, `get_manifest`, `health`, `shutdown` Tools
- [x] `SERVICE.md`, `AGENT.md`, `MCP_ZMQ_STANDARD.md`
- [x] Tests mit pytest (Smoke + Unit)

---

## SM-Producer Anbindung

Der Service kann direkt mit der ME4-SMproducer-3-Pipeline
kommunizieren (HTTP-Bridge auf Port 3001).

Wenn `SM_PRODUCER_ENABLED=true`:
- Tool `trigger_sm_produce` schickt `POST /api/sm-produce` an die Pipeline
- HTTP-Endpoint `/api/sm-produce` macht dasselbe
- Beim Service-Start wird die Pipeline-Erreichbarkeit getestet
  (Warning, falls nicht erreichbar — Service startet trotzdem)

---

## Framie: Live-Status-Display

`Framie` ist das embedded UI-Frontend des Services. Beim Start:

1. Service startet alle Backend-Layer
2. Sobald HTTP-Layer läuft → Framie-UI ist erreichbar
3. Browser öffnet `http://localhost:8770/ui/index.html`
4. Framie-Stream (SSE) liefert Live-Updates aller Jobs
5. Worker-Pool-Status, KPIs und Event-Log werden kontinuierlich aktualisiert

Wird der Service gestartet → startet auch die Framie-UI automatisch.
Wird der Service gestoppt → stoppt auch die Framie-UI.

Der Service-Start ist damit **fester Bestandteil der Schnittstelle**.

---

## Tests

```bash
pytest                            # alle Tests
pytest tests/test_extractor.py    # einzelne Datei
pytest --cov=app                  # Coverage
```

Aktuelle Tests:
- `test_extractor.py` — URL-Parsing (keine Netzwerk-Calls)
- `test_models.py` — Pydantic-Validierung
- `test_auth.py` — API-Key-Auth
- `test_status_tracker.py` — Job-Status + SSE
- `test_loadbalancer.py` — Worker-Selektion
- `test_config.py` — Settings-Validierung
- `test_http_api.py` — HTTP-Smoke-Tests
- `test_zmq_service.py` — MCP-Compliance

---

## Installation

```bash
python -m venv .venv
.venv\Scripts\activate  # Windows
pip install -r requirements.txt
python main.py
```

Voraussetzungen:
- Python 3.11+
- ffmpeg (optional, für Audio-Konvertierung)
