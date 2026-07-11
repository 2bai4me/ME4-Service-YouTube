==============================================================================
ME4-YouTube — AGENT.md
Schnellstart für eine frische Session (Mensch oder Agent)
Repo-Pfad: D:\DEV\ME4-S-youtube
Stand: 2026-07-11
==============================================================================

DAS PROJEKT IN EINEM SATZ
-------------------------
YouTube-Content-Extraction-Service für die ME4-Suite — Video-Download,
Metadaten, Transkripte, Top-Kommentare. Implementiert als MCP-Server
(stdio + ZMQ REQ/REP) + HTTP/REST + Framie-UI mit eingebautem Loadbalancer
und Worker-Pool. Python 3.11+, FastAPI, pyzmq, yt-dlp, youtube-transcript-api.

ARCHITEKTUR IN 3 ZEILEN
-----------------------
Client → HTTP-Front (:8770) + ZMQ-Main (:5570) + ZMQ-LB (:5571)
       → WorkerPool (2 Worker auf :8771+)
       → yt-dlp / youtube-transcript-api / httpx (SM-Producer @ :3001).

TECH-STACK & RAHMENBEDINGUNGEN
-------------------------------
- Python 3.11+, FastAPI, pyzmq, uvicorn (async)
- yt-dlp (Video/Audio/Metadaten), youtube-transcript-api (Captions)
- httpx (async) für SM-Producer- und Worker→Loadbalancer-Kommunikation
- Pydantic v2 für Input-Validierung
- Strukturierte JSON-Logs (app/logging_config.py)
- pytest + pytest-asyncio, pytest-cov für Coverage
- Konventionen: snake_case für Funktionen/Variablen, PascalCase für Klassen
- Tests ohne Netzwerk-Calls (yt-dlp-Output gemockt)

REPO-MAP (was liegt wo)
-----------------------
app/                            Hauptmodule
  config.py                     Settings via Pydantic (.env)
  auth.py                       API-Key Auth (HMAC-compare, constant-time)
  exceptions.py                 8 spezifische Exception-Typen
  logging_config.py             Strukturiertes JSON-Logging
  extractor.py                  YouTube URL-Parser, Metadaten, Kommentare
  downloader.py                 Video/Audio-Download (yt-dlp, async)
  transcriber.py                Transkript (youtube-transcript-api)
  orchestrator.py               Pipeline-Koordinator pro Job
  worker.py                     Sub-Worker (eigener HTTP-Server)
  worker_pool.py                Worker-Sub-Prozesse-Pool
  loadbalancer.py               WorkerPool + MCP-Loadbalancer (ZMQ)
  zmq_service.py                ZMQ REQ/REP Hauptservice
  http_api.py                   FastAPI Router + SSE-Stream
  mcp_stdio.py                  MCP-Server über stdin/stdout
  sm_producer_client.py         SM-Producer HTTP-Client
  status_tracker.py             In-Memory Job-Status + SSE-Bus
  models.py                     Pydantic Request/Response-Modelle
main.py                         Boot-Manager, startet alle Layer in fester Reihenfolge
data/                           Persistenz: jobs/<job_id>.json, youtube_results.db, sessions/, downloads/
docs/
  ARCHITECTURE.md               Design-Prinzipien, Datenflüsse, Security
  SM_PRODUCER_INTEGRATION.md    SM-Producer-Anbindung im Detail
  INTEGRATION.md                UI↔Service-Vertrag (Pilot-Phase 5)
static/                         Framie-UI (index.html, app.js, style.css)
tests/                          pytest-Suite (8 Dateien, ~48 Tests)
scripts/                        Hilfs-Skripte (Smoke, Health)
.env.example                    Vorlage für .env
sidecar-config.env              Lokale API-Keys (gitignored)

WICHTIGE BEGRIFFE (Mental Model)
--------------------------------
- Service-ID = "ME4-YOUTUBE" (Uppercase, MCP-Standard)
- Pipeline-Stage = atomare Verarbeitungs-Stufe mit phase+requires[]
- Worker = Sub-Prozess mit eigenem HTTP-Server + Orchestrator
- Loadbalancer-Strategie = least_loaded (default) | round_robin | random
- Orchestrator = Pipeline-Koordinator pro Job innerhalb eines Workers
- StatusTracker = In-Memory-Ringpuffer (letzte 20 Jobs) + aktive Jobs
- SSE-Stream = /api/framie/stream, 15s keepalive, Live-Updates
- Framie = embedded Live-Status-UI unter /ui/index.html
- AwaitingInput = Service liefert bei fehlender URL ein Envelope statt 400,
  UI rendert Modal mit angeforderten Feldern neu
- _summary = Standard-Response-Envelope mit headline, filesSavedTo, function

QUICK START
-----------
# Setup
cd /d/DEV/ME4-S-youtube
python -m venv .venv
.venv\Scripts\activate            # Windows
pip install -r requirements.txt
copy .env.example .env            # API_KEY anpassen oder leer lassen = Dev-Mode

# Start
python main.py                    # Standard: alle Layer + Framie im Browser
python main.py --no-browser       # ohne Browser-Auto-Open
python main.py --mcp-stdio        # nur MCP-Server (für Agenten wie Claude Code)
python main.py --no-workers       # ohne Worker-Pool (Debug)

# Verify
curl http://localhost:8770/api/health
curl -H "X-API-Key: $API_KEY" -X POST http://localhost:8770/api/metadata \
     -H "Content-Type: application/json" \
     -d '{"url":"https://youtu.be/dQw4w9WgXcQ"}'

# Tests
pytest
pytest --cov=app --cov-report=term-missing

REZEPTE
-------
(A) Einen NEUEN MCP-TOOL hinzufügen
    1. Tool in zmq_service.py:_tools_call registrieren
    2. Manifest-Block in zmq_service.py:get_manifest ergänzen
    3. Handler-Funktion in app/<modul>.py implementieren
    4. Tests in tests/test_<modul>.py
    5. FUNCTIONS.md aktualisieren (1:1-Spiegel von /api/manifest.functions[])

(B) Eine NEUE PIPELINE-STAGE hinzufügen
    1. Stage in /api/manifest (via get_manifest) ergänzen
    2. Handler in orchestrator.py:_run_stages implementieren
    3. StatusTracker.update(job_id, state, step, progress) für Live-Updates
    4. Funktion (die stages[] bündelt) in /api/manifest.functions[] aufnehmen

(C) Worker-Pool-Tuning
    1. .env: WORKER_COUNT, WORKER_BASE_PORT, LOADBALANCER_STRATEGY
    2. Heartbeat-Threshold in app/loadbalancer.py:_check_worker_health
    3. Heartbeat-Loop-Intervall in app/loadbalancer.py:_health_loop

(D) SM-Producer-Anbindung ändern
    1. .env: SM_PRODUCER_URL, SM_PRODUCER_API_KEY, SM_PRODUCER_ENABLED
    2. Client in app/sm_producer_client.py:SMProducerClient
    3. Endpunkt /api/sm-produce in app/http_api.py:sm_produce

(E) Compliance-Check vor PR
    1. Badges in README.md Top-10 (Pilot 0.2)
    2. FUNCTIONS.md reflektiert /api/manifest.functions[] (Pilot 0.5.3)
    3. .env.example enthält alle Variablen aus .env (Pilot 0.5.3)
    4. CHANGELOG.md hat [Unreleased]-Oder-Release-Block (Pilot 0.5.3)
    5. Breaking Changes mit `BREAKING:` markiert (Pilot 0.5.3)

FALLEN & GOTCHAS
----------------
- NIEMALS hartcodierte Ports im Code — immer via .env/Settings (Pydantic).
- API-Key Auth: HMAC-compare in app/auth.py — niemals `==`-String-Vergleich
  für Secrets (Timing-Attack anfällig).
- yt-dlp ist blockierend — IMMER via loop.run_in_executor() in Thread auslagern,
  sonst blockiert der gesamte asyncio-Loop.
- yt-dlp extractor_args: youtube-spezifisch (extractor_args.youtube.max_comments).
  Andere Sites brauchen andere Args.
- Worker-Pool: jeder Worker ist ein eigener Prozess. Sub-Process-Cleanup in
  worker.py:_cleanup MUSS im finally-Block, sonst Zombies bei Crash.
- SSE-Stream: Clients disconnecten oft. Async-Generator muss GeneratorExit
  sauber behandeln, sonst warning "coroutine was never awaited".
- StatusTracker.update() ist thread-safe (asyncio.Lock), aber NIE von einem
  Sync-Thread aus aufrufen — riskant.
- heartbeat_timeout > 30s default — bei Netzwerk-Spikes erhöhen, sonst
  flapping-Workers.
- Loadbalancer-Strategien: round_robin ignoriert Worker-Load, least_loaded
  ist default und für ungleiche Job-Größen besser.
- noplaylist=True bei yt-dlp IMMER — sonst werden versehentlich ganze
  Playlists statt einzelner Videos geladen.
- max_download_size_mb Default 500 — bei größeren Videos überschreiben
  oder Job vorher ablehnen.
- youtube-transcript-api: Fallback-Sprache de→en ist hartcodiert in
  app/transcriber.py. Bei neuen Sprachen: Liste erweitern.

CHECKLISTE VOR COMMIT
--------------------
[ ] npm run typecheck / pytest ist grün
[ ] README.md Badges in Top-10 (Pilot 0.2)
[ ] FUNCTIONS.md reflektiert /api/manifest.functions[] (Pilot 0.5.3)
[ ] .env.example vollständig (alle Variablen aus .env)
[ ] CHANGELOG.md hat Eintrag unter [Unreleased] oder neue Release-Version
[ ] Breaking Changes mit `BREAKING:` markiert
[ ] Keine secrets in .env committed (nur in .env.example mit `***`)
[ ] Keine hartcodierten Ports, IPs oder API-Keys im Code

KONTAKT / STAND
---------------
- Repo: D:\DEV\ME4-S-youtube
- Version: 1.0.0 (siehe SERVICE.md + CHANGELOG.md)
- Maintainer: uwean
- Standards: D:\Entwicklung\ME4-SERVICE-BUS-PILOT.md Sektion 0.5

==============================================================================
ENDE AGENT.md — bei Unklarheiten erst diese Datei + README.md + SERVICE.md lesen,
dann gezielt die genannten Quelldateien, dann erst raten.
==============================================================================