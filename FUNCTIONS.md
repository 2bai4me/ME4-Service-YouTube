# ME4-YouTube — Funktions- & UI-Katalog

> **Service:** `ME4-YOUTUBE` v1.2.001
> **Kategorie:** `content_extraction` (MCP-Server + ZMQ + HTTP + Framie)
> **Subtitle:** *YouTube → Captions → Sections → Slides*
> **Generiert aus:** `app/zmq_service.py` (Manifest), `app/http_api.py` (HTTP-Routen), `app/loadbalancer.py` (LB-Socket), `app/worker.py` (Worker-Sub-Prozesse), `static/index.html` + `app.js` (Framie-UI), `main.py` (CLI).
> **Authentifizierung:** `X-API-Key: <API_KEY>` Header (HMAC-compare in `app/auth.py:23`). `API_KEY=""` in `.env` ⇒ Dev-Mode (offen).

---

## Inhalt

1. [Übersicht — was kann der Service?](#1-übersicht--was-kann-der-service)
2. [UI-Button-Leiste (4 Slots)](#2-ui-button-leiste-4-slots)
3. [Funktionen mit UI-Step-Flow (4 logische Funktionen)](#3-funktionen-mit-ui-step-flow-4-logische-funktionen)
4. [HTTP-API (16 Endpunkte)](#4-http-api-16-endpunkte)
5. [ZMQ-Kommandos (Main 5570 + Loadbalancer 5571)](#5-zmq-kommandos-main-5570--loadbalancer-5571)
6. [CLI-Flags (`main.py`)](#6-cli-flags-mainpy)
7. [Background-Worker / Schedules](#7-background-worker--schedules)
8. [Hinweise & Caveats](#8-hinweise--caveats)

---

## 1. Übersicht — was kann der Service?

**ME4-YouTube** ist ein YouTube-Content-Extraction-Service. Er kann zu einer beliebigen YouTube-URL folgende Dinge holen, speichern und in eine Pipeline gießen:

| Bereich | Was |
|---|---|
| **Metadaten** | Titel, Kanal, Dauer, Tags, Thumbnail, Beschreibung, View-Count, Chapters |
| **Transkript** | Manuell hochgeladene Captions **oder** Auto-Generated Transcripts (`youtube-transcript-api`), sprach-fallback `de` → `en` |
| **Kommentare** | Top-Kommentare via `yt-dlp` mit `extractor_args.youtube.max_comments`, sortiert nach Likes |
| **Download** | Video (mp4) oder nur Audio (m4a) via `yt-dlp`, max. 500 MB (`MAX_DOWNLOAD_SIZE_MB`) |
| **Full-Pipeline (`process`)** | URL → Metadaten + Captions + Comments → Sections splitten → Slides bauen → Export-Paket |
| **SM-Producer-Handoff** | Reicht URL + (optional) Transkript an den externen SM-Producer-Orchestrator weiter |
| **Live-Status** | SSE-Stream `/api/framie/stream` mit `snapshot`, `job.created`, `job.updated`, `job.finished` |
| **Persistenz** | Jeder Job landet als JSON in `data/<job_id>.json` + in SQLite (`data/youtube_results.db`) |

### Netzwerk-Ports

| Port | Zweck | Hört auf |
|---|---|---|
| **8770** | HTTP-API + Framie-UI (`/ui/*`) | `0.0.0.0` |
| **5570** | ZMQ-Hauptservice (REQ/REP, JSON-RPC 2.0) | `0.0.0.0` |
| **5571** | ZMQ-Loadbalancer (REQ/REP, JSON-RPC 2.0) | `0.0.0.0` |
| **5690** | ~~WSSP-15 Heartbeat~~ — **Slot im Manifest, nicht implementiert** (wird im Removal-PR entfernt) | — |
| **8771+** | Worker-Sub-Prozesse (intern, dynamisch) | `127.0.0.1` |

### Worker-Pool

- Standard `WORKER_COUNT=2` Worker-Sub-Prozesse (jeder eigener Port 8771+).
- Loadbalancer-Strategie: `LOADBALANCER_STRATEGY` ∈ `{round_robin, least_loaded, random}`.
- Mit `--no-workers` startet der Service ohne Pool — `/api/process` antwortet dann `503 "no worker available"`.

---

## 2. UI-Button-Leiste (4 Slots)

Die Button-Leiste wird vom **ME4-UI-Baustein** aus dem Service-Manifest (`GET /api/manifest`) gerendert. Die 4 Slots decken die 4 logischen Kernfunktionen ab (Datengewinnung). Die früher zusätzlich im Manifest beworbenen Buttons **Process**, **Trigger SM-Producer**, **Ask PI-Agent**, **Open Notes**, **Open Log** und **Reset Session** wurden mit v1.02.008 entfernt (Variante A — radikal). Die zugehörigen HTTP-Endpunkte (`/api/process`, `/api/sm-produce`) bleiben für direkte Aufrufer weiterhin erreichbar; nur die UI-Werbung im Baustein-Manifest ist entfallen.

| Slot | Button-Name (UI) | Funktion | HTTP-Call | Body-Template (Defaults) | Status |
|:---:|---|---|---|---|:---:|
| **0** | **Get Metadata** | `metadata` | `POST /api/metadata` | `{ "url": "" }` | ✅ aktiv |
| **1** | **Get Transcript** | `transcript` | `POST /api/transcript` | `{ "url": "", "language": "de" }` | ✅ aktiv |
| **2** | **Get Comments** | `comments` | `POST /api/comments` | `{ "url": "", "max_comments": 100 }` | ✅ aktiv |
| **3** | **Download** | `download` | `POST /api/download` | `{ "url": "", "audio_only": false }` | ✅ aktiv |

### Klick-Flow im ME4-UI (Slots 0–3)

1. User klickt Button.
2. Baustein öffnet ein **Formular-Modal** mit den Feldern aus `bodyTemplate` (`url` ist immer Pflicht, weitere optional je nach Funktion).
3. User füllt aus → **Submit** (oder `Esc` zum Abbrechen).
4. Baustein ruft den HTTP-Endpoint mit `X-API-Key` (sofern in `.env` gesetzt).
5. **Modal zeigt Loading-State** (Spinner auf Submit-Button, Modal bleibt offen).
6. Response kommt zurück:
   - **200 + `_summary`** → Modal zeigt **Ergebnis-Card** (`headline.success=true`, Titel, Kanal, …).
   - **200 + `awaitInput`** → Server hat Pflichtfeld vermisst; Modal **rendert sich neu** mit dem `awaitInput.fields`-Array als Eingabefelder (z. B. URL nachfragen).
   - **400** → Inline-Error im Modal: `"Keine gueltige YouTube-URL"` o. ä.
   - **500/502/503** → Modal zeigt Fehlertext + Schließen-Button; User kann erneut absenden.
7. **Bei Erfolg:** Ergebnis-Button *"In Session übernehmen"* (schreibt JSON nach `data/sessions/<sid>/<NN>-<function>/result.{json,md,html}`).
8. Modal kann mit `X` oder `Esc` jederzeit geschlossen werden — die eingegebenen Felder werden verworfen.

---

## 3. Funktionen mit UI-Step-Flow (4 logische Funktionen)

Jede Funktion hat einen deklarativen Step-Flow (`functions[].steps` im Manifest), der im UI als animierte Step-Liste angezeigt wird, sobald die Funktion läuft. Die Schritte kommen mit Icon + Beschreibung. Der Service bietet darüber hinaus zwei weitere MCP-/HTTP-Funktionen (`process`, `trigger_sm_produce`) an, die mit v1.02.008 aus dem UI-Manifest entfernt wurden — siehe [§8 Removed buttons](#removed-buttons-v102008).

### 3.1 `metadata` — *Get Metadata*

> **Beschreibung:** Extrahiere Video-Titel, Kanal, Dauer, Tags.
> **Pipeline-Stages:** `parse_url` → `fetch_metadata`
> **HTTP:** `POST /api/metadata`
> **ZMQ-Tool:** `get_metadata`

| # | Step-Name | Icon | Was passiert |
|:--:|---|---|---|
| 1 | URL aufrufen | 🔗 | Service prüft die YouTube-URL (Regex auf `v=…` oder `/…`, Video-ID-Extraktion). |
| 2 | Daten abrufen | 📥 | `yt-dlp` extrahiert Video-Informationen (info_dict, gefiltert). |
| 3 | Daten speichern | 💾 | Ergebnis als JSON + MD nach `data/sessions/<sid>/<NN>-get-metadata/result.{json,md,html}` schreiben. |

**Request:**
```json
{ "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "sessionId": "optional" }
```

**Response (200):**
```json
{
  "_summary": {
    "filesSavedTo": ["…/result.json", "…/result.md"],
    "jsonPath": "…/result.json",
    "mdPath":   "…/result.md",
    "headline": { "success": true, "title": "…", "channel": "…", "duration_sec": 213, "view_count": 1234567 },
    "function": "get-metadata"
  }
}
```

**Response (`awaitInput`, URL fehlt):**
```json
{
  "awaitInput": {
    "title": "🎬 YouTube-URL eingeben",
    "fields": [{ "name": "url", "type": "url", "required": true, "placeholder": "https://www.youtube.com/watch?v=…" }]
  }
}
```

---

### 3.2 `transcript` — *Get Transcript*

> **Beschreibung:** Captions oder Auto-Generated Transkript holen.
> **Pipeline-Stages:** `parse_url` → `fetch_captions`
> **HTTP:** `POST /api/transcript`
> **ZMQ-Tool:** `get_transcript`

| # | Step-Name | Icon | Was passiert |
|:--:|---|---|---|
| 1 | URL aufrufen | 🔗 | Service prüft die YouTube-URL. |
| 2 | Captions abrufen | 📝 | `youtube-transcript-api` lädt Captions in der gewünschten Sprache; Fallback auf `en`, wenn die gewählte Sprache fehlt. |
| 3 | Daten speichern | 💾 | Snippet-Liste + Sprachinfo als JSON+MD persistieren. |

**Request:**
```json
{ "url": "https://youtu.be/dQw4w9WgXcQ", "language": "de", "sessionId": "optional" }
```

**Response (200):**
```json
{
  "_summary": {
    "filesSavedTo": ["…/result.json", "…/result.md"],
    "headline": { "success": true, "video_id": "dQw4w9WgXcQ", "language": "de", "is_generated": true, "snippet_count": 412 },
    "function": "get-transcript"
  }
}
```

---

### 3.3 `comments` — *Get Comments*

> **Beschreibung:** Top-Kommentare des Videos laden.
> **Pipeline-Stages:** `parse_url` → `fetch_comments`
> **HTTP:** `POST /api/comments`
> **ZMQ-Tool:** `get_comments`

| # | Step-Name | Icon | Was passiert |
|:--:|---|---|---|
| 1 | URL aufrufen | 🔗 | Service prüft die YouTube-URL. |
| 2 | Kommentare laden | 💬 | `yt-dlp` mit `extractor_args.youtube.max_comments`; sortiert nach `top` (Likes). |
| 3 | Daten speichern | 💾 | Kommentar-Liste als JSON+MD persistieren. |

**Request:**
```json
{ "url": "https://youtu.be/dQw4w9WgXcQ", "max_comments": 100, "sessionId": "optional" }
```

**Response (200):**
```json
{
  "_summary": {
    "filesSavedTo": ["…/result.json", "…/result.md"],
    "headline": { "success": true, "video_id": "dQw4w9WgXcQ", "count": 100, "truncated": false },
    "function": "get-comments"
  }
}
```

---

### 3.4 `download` — *Download*

> **Beschreibung:** Video (und optional Audio) herunterladen.
> **Pipeline-Stages:** `parse_url` → `download_video` → `convert_audio`
> **HTTP:** `POST /api/download`
> **ZMQ-Tool:** `download`

| # | Step-Name | Icon | Was passiert |
|:--:|---|---|---|
| 1 | URL aufrufen | 🔗 | Service prüft die YouTube-URL. |
| 2 | Video herunterladen | 📥 | `yt-dlp` lädt das Medium im gewählten Format-String (Default `bestvideo[ext=mp4]+bestaudio[ext=m4a]/best`). |
| 3 | Format konvertieren | 🔄 | Bei `audio_only=true` wird das Video in `.m4a` (Audio-only) konvertiert. |
| 4 | Datei speichern | 💾 | Datei landet im konfigurierten Download-Verzeichnis (`data/downloads/` o. ä.); Metadaten als JSON. |

**Request:**
```json
{ "url": "https://youtu.be/dQw4w9WgXcQ", "audio_only": false, "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best", "sessionId": "optional" }
```

**Response (200):**
```json
{
  "_summary": {
    "filesSavedTo": ["…/result.json"],
    "file": "Rick Astley - Never Gonna Give You Up.mp4",
    "headline": { "success": true, "title": "…", "duration_sec": 213, "size_mb": 12.4, "format_id": "18" },
    "function": "download"
  }
}
```

**Limit:** `MAX_DOWNLOAD_SIZE_MB=500` — größere Dateien werden abgelehnt.

---

## 4. HTTP-API (16 Endpunkte)

Alle Endpunkte werden vom FastAPI-App in `app/http_api.py` bereitgestellt. Auth-Pflicht via `X-API-Key`-Header wenn `API_KEY != ""` in `.env`.

| # | Method | Path | Auth | Handler (Datei:Zeile) | Kurzbeschreibung |
|:--:|--------|------|:--:|---|---|
| 1 | `GET` | `/` | – | `root` (`http_api.py:120`) | Service-Stammdaten + Framie-/Docs-Links |
| 2 | `GET` | `/api/health` | – | `health` (`http_api.py:129`) | Health-Check + Worker-Pool-Status |
| 3 | `GET` | `/api/manifest` | – | `manifest` (`http_api.py:142`) | UI-Manifest für ME4-UI-Baustein |
| 4 | `GET` | `/api/status` | – | `status` (`http_api.py:146`) | Live-Snapshot aller Jobs (active + recent + totals) |
| 5 | `GET` | `/api/framie/stream` | – | `framie_stream` (`http_api.py:150`) | SSE-Bus (15s keepalive) |
| 6 | `POST` | `/api/process` | 🔑 | `process` (`http_api.py:170`) | Volle Pipeline (nutzt Worker-Pool) |
| 7 | `GET` | `/api/results` | – | `list_results` (`http_api.py:212`) | Letzte Persistenz-Einträge (DB) |
| 8 | `GET` | `/api/results/{job_id}` | – | `get_result` (`http_api.py:221`) | Einzelnes Ergebnis (DB) |
| 9 | `POST` | `/api/metadata` | 🔑 | `metadata` (`http_api.py:234`) | Metadaten + Description |
| 10 | `POST` | `/api/transcript` | 🔑 | `transcript` (`http_api.py:252`) | Transkript (Fallback `de`→`en`) |
| 11 | `POST` | `/api/comments` | 🔑 | `comments` (`http_api.py:279`) | Top-Kommentare (sortiert nach Likes) |
| 12 | `POST` | `/api/download` | 🔑 | `download` (`http_api.py:304`) | Video/Audio herunterladen (max 500 MB) |
| 13 | `POST` | `/api/sm-produce` | 🔑 | `sm_produce` (`http_api.py:343`) | SM-Producer-Handoff (502 wenn SM down) |
| 14 | `GET` | `/docs` | – | (FastAPI default) | Swagger-UI |
| 15 | `GET` | `/openapi.json` | – | (FastAPI default) | OpenAPI 3.x Schema |
| 16 | `*` | `/ui/...` | – | `StaticFiles(html=True)` (`http_api.py:369`) | Statische UI-Dateien aus `static/` |

### Worker-Sub-Prozess-Endpunkte (intern, Ports 8771+)

| Method | Path | Auth | Was |
|---|---|---|---|
| `GET` | `/` | – | Worker-Stammdaten (`worker_id`, `status`, `uptime_sec`) |
| `GET` | `/health` | – | Worker-Health (`current_load`, `total_processed`) |
| `POST` | `/process` | `X-API-Key` | Führt `Orchestrator.process` aus, publiziert SSE-Events |

---

## 5. ZMQ-Kommandos (Main 5570 + Loadbalancer 5571)

Beide Sockets sprechen **REQ/REP JSON-RPC 2.0**. Methoden: `initialize`, `tools/list`, `tools/call`. Bei `tools/call` MUSS `api_key` in `arguments` stehen (außer bei `public`-Tools).

### 5.1 Main-Socket — `tcp://*:5570` (`app/zmq_service.py`)

| Tool-Name | Auth | Was es tut |
|---|:--:|---|
| `ping` | – | Health-Ping (gibt `status: "ok"`, `service`, `version` zurück) |
| `get_manifest` | – | UI-Manifest (wie `GET /api/manifest`) |
| `health` | – | Detaillierter Service-Status inkl. Worker-Pool |
| `get_status_snapshot` | – | Live-Job-Status (active + recent + totals) |
| `get_metadata` | 🔑 | YouTube-Metadaten + Description |
| `get_transcript` | 🔑 | YouTube-Transkript |
| `get_comments` | 🔑 | Top-Kommentare |
| `download` | 🔑 | Video/Audio herunterladen |
| `process` | 🔑 | Volle Pipeline (wird intern via `httpx` an einen Worker weitergereicht) |
| `trigger_sm_produce` | 🔑 | Reicht Job an `http://<SM_PRODUCER_URL>/api/sm-produce` weiter |
| `shutdown` | 🔑 | Geordneter Service-Shutdown (0.5s grace, dann `pool.stop()`) |

**Beispiel (Python):**
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
            "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "include_description": True, "include_transcript": True,
            "include_comments": True, "language": "de", "max_comments": 100,
            "api_key": "<API_KEY>"
        }
    }
})
print(sock.recv_json())
```

### 5.2 Loadbalancer-Socket — `tcp://*:5571` (`app/loadbalancer.py:135`)

Identisches REQ/REP-Protokoll, **reduzierte** Tool-Liste — leitet Jobs anhand der `LOADBALANCER_STRATEGY` (`round_robin` | `least_loaded` | `random`) an einen freien Worker weiter. Antwort kommt vom Worker (nicht vom LB).

| Tool-Name | Auth | Was es tut |
|---|:--:|---|
| `ping` | – | LB-Health-Ping (`status: "ok"`, `service: "ME4-YOUTUBE-LB"`) |
| `tools/list` | – | Liste der LB-Tools |
| `health` / `status` | – | Pool-Status (welche Worker laufen, Load-Verteilung) |
| `process` | 🔑 | Volle Pipeline → an einen freien Worker (`Orchestrator.process`) |

LB-Antwort ist die Worker-Antwort (kein eigenes `_summary`).

---

## 6. CLI-Flags (`main.py`)

| Flag | Effekt |
|---|---|
| `--mcp-stdio` | Startet im **MCP stdio mode** (für Agenten wie Claude / Cursor / Hermes). JSON-RPC über stdin/stdout statt ZMQ-Socket. |
| `--no-workers` | Startet **ohne Worker-Pool**. `/api/process` antwortet dann `503 "no worker available"`; ZMQ-`process`-Tool ebenfalls. |
| `--no-browser` | Framie-UI wird **nicht automatisch im Browser** geöffnet. |
| `--port <int>` | HTTP-Port überschreiben (Default `8770`). |
| `--host <str>` | HTTP-Host überschreiben (Default `0.0.0.0`). |

**Beispiele:**
```bash
# Standard-Start (Worker-Pool + Browser)
python main.py

# Dev: ohne Worker-Pool
python main.py --no-workers --no-browser --port 8770

# MCP-Server für Agent Zero
python main.py --mcp-stdio
```

---

## 7. Background-Worker / Schedules

| Worker | Gestartet von | Loop | Was er tut |
|---|---|---|---|
| **HTTP-API-Lifespan** | `app/http_api.py` (`lifespan`-Context) | App-Lifetime | Bindet FastAPI auf `:8770`, mountet `/ui/*` StaticFiles, startet SSE-Stream. |
| **SSE-Stream-Broadcaster** | `app/http_api.py` | App-Lifetime | Pusht `status_tracker`-Snapshots alle 1s an alle SSE-Clients. |
| **ZMQ-Main-Service** | `app/main.py` (Boot) | App-Lifetime | Bindet `tcp://*:5570`, behandelt REQ/REP. |
| **ZMQ-Loadbalancer** | `app/main.py` (Boot) | App-Lifetime | Bindet `tcp://*:5571`, Health-Loop pingt Worker alle 5s. |
| **Worker-Pool** | `app/worker_pool.py` (Boot) | App-Lifetime | Startet `WORKER_COUNT` Sub-Prozesse, je Port 8771+; Restart bei Crashes. |
| **Worker-Health-Loop** | `app/loadbalancer.py:54-66` | Pro Worker | Pingt Worker-`/health` alle 5s; setzt `available=false` bei Timeout. |
| **Status-Tracker** | `app/status_tracker.py` | App-Lifetime | In-Memory-Ringpuffer (letzte 20 Jobs) + aktive Jobs; wird per SSE + HTTP exponiert. |
| **Periodic-Saver (im Worker)** | `app/worker.py` | Pro Job | Schreibt Job-Ergebnis in `data/<job_id>.json` + SQLite-Row nach `process`-Abschluss. |

**Keine klassischen Cron-Schedules** — der Service ist event-driven (HTTP/ZMQ-Requests). Hintergrund-Loops sind nur Liveness- und SSE-Broadcasting.

---

## 8. Hinweise & Caveats

### Removed buttons (v1.02.008)

Mit v1.02.008 wurden 6 von 10 UI-Buttons aus dem Baustein-Manifest entfernt („Variante A — radikal"):

| Slot | Button | Ziel | Status |
|:---:|---|---|---|
| ~~4~~ | ~~Process~~ | `POST /api/process` | Backend-Endpoint bleibt erreichbar; nur UI-Werbung entfernt. |
| ~~5~~ | ~~Trigger SM-Producer~~ | `POST /api/sm-produce` | Backend-Endpoint bleibt erreichbar; nur UI-Werbung entfernt. |
| ~~6~~ | ~~Ask PI-Agent~~ | `POST /__pi_agent__` | Route existierte im HTTP-API nicht (404). |
| ~~7~~ | ~~Open Notes~~ | `GET /notes/export` | Route existierte im HTTP-API nicht (404). |
| ~~8~~ | ~~Open Log~~ | `GET /log/recent` | Route existierte im HTTP-API nicht (404). |
| ~~9~~ | ~~Reset Session~~ | `POST /session/reset` | Route existierte im HTTP-API nicht (404). |

Die Service-Seite des ME4-Bausteins (`ME4-UI`) bekommt einen separaten PR, der die Slot-Stub-Logik entfernt und die jetzt nur 4 Buttons umfassende Button-Leiste verdrahtet. Aus UI-Sicht bleiben die 4 Kernfunktionen voll funktional.

### ⚠️ WSSP-15 Heartbeat (Slot im Manifest, in PR zur Entfernung)

Im Manifest steht `"wssp15": settings.wssp15_port` in `ports[]`. Das `wssp15`-Paket existiert weder auf PyPI noch im Venv (siehe `explore-wssp15-missing` vom 2026-07-10). Der Heartbeat-Import in `main.py` ist in `try/except Exception` gewrappt — der Service läuft im "degraded mode" ohne Heartbeat. **Wird im PR `chore/remove-wssp15` (in Review) komplett entfernt** (Manifest-Eintrag, Import, Banner-Zeilen, Tests, Docs).

### ⚠️ `awaitInput` als alternative Eingabe-Aufforderung

Die 4 "frühen" Funktionen (`metadata`, `transcript`, `comments`, `download`) und `sm-produce` liefern bei fehlender URL **keinen 400**, sondern ein `awaitInput`-Envelope (siehe §3.1). Das ist Absicht — der Baustein soll das Modal mit den angeforderten Feldern neu rendern. Wer die Endpoints programmatisch (z. B. via curl) aufruft, MUSS diesen Pfad mitbehandeln.

### ⚠️ Dev-Mode ohne API-Key

Wenn `API_KEY=""` in `.env` gesetzt ist, gilt `X-API-Key`-Header als optional und der Service ist offen. **Niemals in Production so deployen.** Auth-Compare ist HMAC-basiert (`hmac.compare_digest`), also nicht timing-attack-anfällig.

### 📁 Persistenz-Layout

```
data/
├── <job_id>.json                     # Pro `process`-Job
├── youtube_results.db                # SQLite (alle Jobs, queryable via /api/results)
├── downloads/                        # Video/Audio-Downloads
└── sessions/
    └── <session_id>/
        └── <NN>-<function>/          # Framie-UI-Session-Ergebnisse
            ├── result.json
            ├── result.md
            └── result.html
```

### 🔗 Externe Skripte (nicht Teil der Service-Surface)

- `scripts/yt_bridge.py` (Port 3002) — separater Helper, läuft als eigener Prozess, nicht in `main.py` eingebunden.
- `scripts/yt_process_frame.py` (Port 3003) — separater Helper, dito.

Beide nutzen den Service nur als HTTP-Client.

---

*Stand: 2026-07-10 · Quelle: explorer's `explore-functions-catalog` (MiniMax-M3) + direkte Reads von `app/zmq_service.py`, `app/http_api.py`, `static/index.html`, `static/app.js`, `main.py`.*
