# ME4-YouTube

> **🧠 Standards:** Dieses Projekt folgt den ME4-Service-Bus-Standards v1.0.  
> 📖 **Verbindlich:** [HUB-Thought im openBrain](http://localhost:9100/thought/a2d183a3-e6f8-48ab-9ba1-d7a9eae2399e) — die Single source of truth.  
> ⚠️ **Abweichungen** MÜSSEN in einem PR begründet werden.

[![ME4-Standard](https://img.shields.io/badge/ME4-Standard-v1.0-blue)](D:/Entwicklung/ME4-SERVICE-BUS-PILOT.md)
[![openBrain](https://img.shields.io/badge/openBrain-HUB-green)](http://localhost:9100/thought/a2d183a3-e6f8-48ab-9ba1-d7a9eae2399e)
[![SOA-konform](https://img.shields.io/badge/SOA-konform-ja-brightgreen)](D:/Entwicklung/ME4-SERVICE-BUS-PILOT.md)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)


> **Service-ID:** `ME4-YOUTUBE`
> **Version:** 1.0.0
> **Schnittstellen:** MCP (stdio + ZMQ REQ/REP) + HTTP/REST + Framie-UI

## TL;DR

- **Was:** YouTube-Content-Extraction-Service für die ME4-Suite — Video-Download, Metadaten, Transkripte, Top-Kommentare
- **Capabilities:** `video_download`, `metadata_extraction`, `transcript_extraction`, `comments_extraction`, `translation`, `load_balancing`, `live_status_stream`, `sm_producer_integration`
- **Ports:** HTTP 8770, ZMQ-Main 5570, ZMQ-Loadbalancer 5571, Worker-Pool 8771+
- **Health:** `GET http://localhost:8770/api/health`
- **Standard-Vertrag:** MCP + ZMQ REQ/REP (JSON-RPC 2.0), HMAC-compare API-Key Auth

## Schnellstart

YouTube Content Extraction Service für die ME4-Suite:
- **Download** — Video- und Audio-Download via `yt-dlp`
- **Beschreibung** — Vollständige Metadaten inkl. Description
- **Transkript** — Manuell oder Auto-Generated, Multi-Language
- **Kommentare** — Top-Kommentare via `yt-dlp`
- **Loadbalancer-MCP** — Parallele Worker-Instanzen mit Health-Monitoring
- **Framie-UI** — Embedded Live-Status-Display

---

```bash
# Voraussetzungen: Python 3.11+, ffmpeg (optional, für Audio-Konvertierung)

# Klonen / Installieren
cd D:\Entwicklung\ME4-YouTube
python -m venv .venv
.venv\Scripts\activate           # Windows
# source .venv/bin/activate      # macOS/Linux
pip install -r requirements.txt

# Konfiguration (Beispiel kopieren, anpassen)
copy .env.example .env           # Windows
# cp .env.example .env           # macOS/Linux

# Starten
python main.py

# ODER (öffnet Framie-UI nicht automatisch)
python main.py --no-browser
```

Beim Start öffnet sich automatisch die **Framie-UI** im Browser unter
[http://localhost:8770/ui/index.html](http://localhost:8770/ui/index.html).

---

## Schnittstellen

| Schnittstelle | Port | Zweck |
|---|---|---|
| **HTTP / REST** | `8770` | Browser, Menschen, externe Tools |
| **ZMQ Main** | `5570` | MCP-Service-Endpoint |
| **ZMQ Loadbalancer** | `5571` | MCP-Loadbalancer (parallele Worker) |
| **Worker-Pool** | `8771+` | N parallele Worker-Instanzen (default: 2) |

### MCP-Tools (ZMQ + stdio)

| Tool | Beschreibung | Auth |
|---|---|---|
| `ping` | Service-Health | public |
| `get_manifest` | UI-Manifest für Cockpit | public |
| `health` | Detaillierter Status inkl. Worker-Pool | public |
| `get_status_snapshot` | Live-Job-Status | public |
| `get_metadata` | YouTube Metadaten + Description | 🔑 |
| `get_transcript` | YouTube Transkript | 🔑 |
| `get_comments` | YouTube Top-Kommentare | 🔑 |
| `download` | Video/Audio herunterladen | 🔑 |
| `process` | Komplette Pipeline (alle 4 Features) | 🔑 |
| `trigger_sm_produce` | SM-Producer anstoßen | 🔑 |
| `shutdown` | Geordneter Shutdown | 🔑 |

### HTTP-Endpunkte

| Pfad | Methode | Beschreibung |
|---|---|---|
| `/` | GET | Service-Info |
| `/docs` | GET | OpenAPI/Swagger UI |
| `/api/health` | GET | Health (public) |
| `/api/manifest` | GET | UI-Manifest (public) |
| `/api/status` | GET | Live-Job-Status (public) |
| `/api/framie/stream` | GET | SSE-Stream für Framie-UI (public) |
| `/api/process` | POST | Komplette Verarbeitung (🔑) |
| `/api/metadata` | POST | Nur Metadaten (🔑) |
| `/api/transcript` | POST | Nur Transkript (🔑) |
| `/api/comments` | POST | Nur Kommentare (🔑) |
| `/api/download` | POST | Video-Download (🔑) |
| `/api/sm-produce` | POST | SM-Producer triggern (🔑) |
| `/ui/index.html` | GET | Framie Live-Status-Display |

🔑 = `X-API-Key` Header erforderlich (oder Dev-Mode wenn `API_KEY=""`)

---

## Beispiele

### HTTP (curl)

```bash
# Metadaten + Beschreibung
curl -X POST http://localhost:8770/api/metadata \
  -H "X-API-Key: <YOUR_API_KEY>" \
  -H "Content-Type: application/json" \
  -d '{"url":"https://youtu.be/dQw4w9WgXcQ"}'

# Komplette Verarbeitung (alle Features)
curl -X POST http://localhost:8770/api/process \
  -H "X-API-Key: <YOUR_API_KEY>" \
  -H "Content-Type: application/json" \
  -d '{
    "url":"https://youtu.be/dQw4w9WgXcQ",
    "download":false,
    "include_description":true,
    "include_transcript":true,
    "include_comments":true,
    "language":"de",
    "max_comments":100
  }'
```

### ZMQ (Python)

```python
import zmq, json

ctx = zmq.Context()
sock = ctx.socket(zmq.REQ)
sock.connect("tcp://127.0.0.1:5570")

sock.send_json({
    "jsonrpc": "2.0", "id": 1, "method": "tools/call",
    "params": {
        "name": "process",
        "arguments": {
            "url": "https://youtu.be/dQw4w9WgXcQ",
            "api_key": "<YOUR_API_KEY>",
        }
    }
})
print(sock.recv_json())
```

### MCP stdio (Claude Code / Agenten)

```json
{
  "mcpServers": {
    "me4-youtube": {
      "command": "python",
      "args": ["D:/Entwicklung/ME4-YouTube/main.py", "--mcp-stdio"]
    }
  }
}
```

### Loadbalancer-MCP (parallele Verarbeitung)

Der Service bringt einen eingebauten Loadbalancer-MCP mit. Agenten
können Jobs direkt an den Loadbalancer schicken, der sie auf freie
Worker verteilt:

```python
sock.connect("tcp://127.0.0.1:5571")
sock.send_json({
    "jsonrpc": "2.0", "id": 1, "method": "tools/call",
    "params": {
        "name": "process",
        "arguments": {
            "url": "https://youtu.be/dQw4w9WgXcQ",
            "api_key": "<YOUR_API_KEY>",
        }
    }
})
```

Strategien: `round_robin`, `least_loaded`, `random` (default: `least_loaded`)

---

## SM-Producer Anbindung

Der Service kann direkt die SM-Producer-Pipeline (ME4-SMproducer-3) anstoßen:

```bash
curl -X POST http://localhost:8770/api/sm-produce \
  -H "X-API-Key: <YOUR_API_KEY>" \
  -H "Content-Type: application/json" \
  -d '{
    "url":"https://youtu.be/dQw4w9WgXcQ",
    "transcript":"Volltext...",
    "language":"de",
    "workflow":"default"
  }'
```

Der Aufruf wird an `http://localhost:3001/api/sm-produce` weitergeleitet.
Konfiguration via `SM_PRODUCER_URL` und `SM_PRODUCER_API_KEY` in `.env`.

---

## Framie-UI

Beim Start des Services öffnet sich automatisch die Framie-UI im Browser:
- KPIs: aktive Jobs, erledigt, Fehler, Worker-Status
- Live-Stream über Server-Sent Events
- Worker-Liste mit Idle/Busy/Down-Status
- Letzte 15 Jobs in Tabelle
- Event-Log

URL: `http://localhost:8770/ui/index.html`

---

## Tests

```bash
pip install pytest pytest-asyncio
pytest

# Mit Coverage
pip install pytest-cov
pytest --cov=app --cov-report=term-missing
```

---

## Konfiguration (.env)

Siehe [`.env.example`](.env.example) für alle Optionen.

Wichtige Variablen:
- `API_KEY` — API-Key (leer = Dev-Mode)
- `WORKER_COUNT` — Anzahl paralleler Worker (default: 2)
- `LOADBALANCER_STRATEGY` — `round_robin` | `least_loaded` | `random`
- `SM_PRODUCER_URL` — SM-Producer-Pipeline-URL
- `DOWNLOAD_DIR` — Zielordner für Downloads

---

## Schnittstellen-Standard

Konform zu [MCP_ZMQ_STANDARD.md](./MCP_ZMQ_STANDARD.md):
- ZMQ REQ/REP mit JSON-RPC 2.0
- API-Key Auth
- UI-Manifest
- Standard-Tools (`ping`, `get_manifest`, `health`, `shutdown`)

---

## Architektur

```
┌──────────────────────────────────────────────────────────┐
│ ME4-YouTube (Service-ID: ME4-YOUTUBE)                    │
│                                                          │
│  ┌────────────────┐  ┌─────────────────┐                │
│  │  HTTP API      │  │  ZMQ Main       │                │
│  │  :8770         │  │  :5570          │                │
│  │  + Framie-UI   │  │  MCP REQ/REP    │                │
│  └────────┬───────┘  └────────┬────────┘                │
│           │                   │                         │
│           └─────────┬─────────┘                         │
│                     ▼                                   │
│           ┌─────────────────────┐                       │
│           │  WorkerPool         │                       │
│           │  (Load-Balancer)    │                       │
│           │  ZMQ :5571          │◄──── Loadbalancer-MCP  │
│           └─────────┬───────────┘                       │
│                     │                                   │
│         ┌───────────┼───────────┐                       │
│         ▼           ▼           ▼                       │
│    ┌─────────┐ ┌─────────┐ ┌─────────┐                  │
│    │worker-01│ │worker-02│ │worker-03│  (jeweils        │
│    │  :8771  │ │  :8772  │ │  :8773  │   Orchestrator)  │
│    └─────────┘ └─────────┘ └─────────┘                  │
│                                                          │
│  ┌────────────────┐                                        │
│  │  SM-Producer   │                                        │
│  │  HTTP :3001    │                                        │
│  └────────────────┘                                        │
└──────────────────────────────────────────────────────────┘
```

Jeder Worker hat:
- eigenen HTTP-Server (für eingehende Jobs vom Loadbalancer)
- einen `Orchestrator` (führt die Pipeline aus)
- Status-Updates landen im globalen `StatusTracker` → Framie-Stream

---

## Verweise

- [`SERVICE.md`](SERVICE.md) — Schnittstellen-Spezifikation (HTTP/ZMQ/MCP/Auth)
- [`FUNCTIONS.md`](FUNCTIONS.md) — Funktions-Katalog mit UI-Step-Flows (1:1-Spiegel von `/api/manifest.functions[]`)
- [`SERVICE_START.md`](SERVICE_START.md) — Boot-Sequenz, Lifecycle, Deployment
- [`AGENT.md`](AGENT.md) — Briefing für autonome Agenten
- [`ARCHITECTURE.md`](ARCHITECTURE.md) — Design-Prinzipien, Datenflüsse, Security-Modell
- [`docs/SM_PRODUCER_INTEGRATION.md`](docs/SM_PRODUCER_INTEGRATION.md) — SM-Producer-Anbindung im Detail
- [`docs/INTEGRATION.md`](docs/INTEGRATION.md) — UI↔Service-Vertrag (Pilot-Phase 5)
- [`MCP_ZMQ_STANDARD.md`](MCP_ZMQ_STANDARD.md) — verbindlicher MCP+ZMQ-Standard für alle ME4-Services
- [`CHANGELOG.md`](CHANGELOG.md) — Versionierte Änderungshistorie (Keep-a-Changelog 1.1)
- [`LICENSE`](LICENSE) — MIT
- [`CONTRIBUTING.md`](CONTRIBUTING.md) — wie du beitragen kannst
- [`SECURITY.md`](SECURITY.md) — Sicherheitslücken melden
- [`CODEOWNERS`](CODEOWNERS) — Review-Verantwortlichkeiten
- [`.editorconfig`](.editorconfig) / [`.gitattributes`](.gitattributes) — Code- und Whitespace-Standards
- [`.github/ISSUE_TEMPLATE/`](.github/ISSUE_TEMPLATE/) — strukturierte Bug-Reports, Feature-Requests, Docs-Issues
- [`.github/workflows/docs-lint.yml`](.github/workflows/docs-lint.yml) — CI-Guard gegen Pilot-0.5-Verstöße

Pilot-Standards: `D:\Entwicklung\ME4-SERVICE-BUS-PILOT.md` Sektion 0.5 (Dokumentations-Pflichtstruktur).
