# SERVICE_START.md — Boot-Sequenz & Service-Lifecycle

> **Verbindlich** für alle, die `ME4-YouTube` deployen oder betreiben.

---

## 1. Service-Start als fester Bestandteil der Schnittstelle

Der `ME4-YouTube`-Service ist so konzipiert, dass ein einziger
`python main.py`-Aufruf **alle** Schnittstellen-Layer in fester
Reihenfolge startet. Der Framie-Status-Stream ist Teil dieser
Boot-Sequenz — er ist nicht optional.

```
┌─────────────────────────────────────────────────────────────┐
│                  python main.py                            │
└─────────────────────────┬───────────────────────────────────┘
                          ▼
            ┌────────────────────────────┐
            │  1. Logging init           │
            └──────────┬─────────────────┘
                       ▼
            ┌────────────────────────────┐
            │  2. Worker-Pool starten    │  (2 Worker auf :8771, :8772)
            └──────────┬─────────────────┘
                       ▼
            ┌────────────────────────────┐
            │  3. ZMQ-Loadbalancer :5571 │  ← MCP-konform
            └──────────┬─────────────────┘
                       ▼
            ┌────────────────────────────┐
            │  4. ZMQ-Hauptservice :5570 │  ← MCP-konform
            └──────────┬─────────────────┘
                       ▼
            ┌────────────────────────────┐
            │  5. WSSP-15 Heartbeat :5690│
            └──────────┬─────────────────┘
                       ▼
            ┌────────────────────────────┐
            │  6. HTTP-API + Framie :8770│  ← Framie-UI unter /ui/
            └──────────┬─────────────────┘
                       ▼
            ┌────────────────────────────┐
            │  7. SM-Producer testen     │  (non-blocking)
            └──────────┬─────────────────┘
                       ▼
            ┌────────────────────────────┐
            │  8. Framie im Browser      │  (wenn --no-browser nicht gesetzt)
            └──────────┬─────────────────┘
                       ▼
            ┌────────────────────────────┐
            │  ✅  SERVICE BEREIT        │
            └────────────────────────────┘
```

**Wichtig**: Wird der Service gestartet, startet automatisch auch
die Framie-UI. Wird der Service gestoppt, stoppt auch die UI.

---

## 2. Kommandozeilen-Optionen

```bash
python main.py                       # Standard: alle Layer
python main.py --mcp-stdio           # Nur MCP-stdio (für Agenten)
python main.py --no-workers          # Ohne Worker-Pool
python main.py --no-browser          # Framie-UI nicht im Browser öffnen
python main.py --port 8888           # HTTP-Port überschreiben
python main.py --host 0.0.0.0        # HTTP-Host überschreiben

# Kombiniert
python main.py --no-browser --port 8888
```

### Modi

| Modus | Wann |
|---|---|
| **Standard** (`python main.py`) | Service-Start, Produktion, Entwicklung |
| **`--mcp-stdio`** | Agent-Integration (Claude Code, etc.) — kein ZMQ/HTTP, nur stdin/stdout |
| **`--no-workers`** | Service ohne Pool (z. B. für Debug) — Loadbalancer-Requests würden fehlschlagen |

---

## 3. Startup-Reihenfolge (verbindlich)

Beim Start MÜSSEN die Layer in dieser Reihenfolge initialisiert werden:

1. **Logging** (app/logging_config.py → setup_logging)
2. **Worker-Pool** (app/loadbalancer.py → WorkerPool.start)
3. **ZMQ-Loadbalancer** (app/loadbalancer.py → LoadBalancerZMQ.start)
4. **ZMQ-Hauptservice** (app/zmq_service.py → ZMQService.start)
5. **WSSP-15 Heartbeat** (wssp15/heartbeat_emitter.py)
6. **HTTP-API + Framie** (app/http_api.py → build_app)
7. **SM-Producer Anbindung** (app/sm_producer_client.py)
8. **Framie-Browser-Öffnung** (webbrowser.open)

Diese Reihenfolge ist hartcodiert in `main.py` (Klasse `ServiceBootstrap.boot`)
und darf nicht geändert werden ohne Absprache mit dem CIO.

---

## 4. Status-Anzeige via Framie (verbindlich)

Der Framie-Stream ist **fester Bestandteil der Schnittstelle**.
Das bedeutet:

- Die Framie-UI läuft IMMER mit, sobald der Service gestartet ist
- Der SSE-Stream `/api/framie/stream` ist IMMER aktiv
- Der Status-Tracker (`app/status_tracker.py`) wird von ALLEN
  Pipeline-Komponenten (Extractor, Downloader, Transcriber,
  Worker) befüllt
- Die Framie-UI zeigt den Status **direkt vom Service aus** an
  (kein externer Service nötig)

### Was wird angezeigt?

- **Aktive Jobs** mit Step, Progress, Worker-ID
- **Worker-Pool** mit Idle/Busy/Down-Status, Load, Total Processed
- **KPIs** (Aktive/Erledigt/Fehler/Worker)
- **Letzte 15 Jobs** in Tabelle (Job-ID, URL, Worker, Status, Dauer)
- **Live Event-Log** (Tail der letzten 100 Events)

### Wo wird angezeigt?

- Browser: `http://localhost:8770/ui/index.html`
- Wird beim Start automatisch geöffnet (außer `--no-browser`)
- Funktioniert auch hinter Reverse-Proxy (SSE-Passthrough erforderlich)

---

## 5. Loadbalancer-MCP (verbindlich)

Der Service startet **immer** einen eingebauten MCP-Loadbalancer auf
Port `LOADBALANCER_ZMQ_PORT` (default: 5571). Dieser ist Teil der
Boot-Sequenz.

**Zweck**: Mehrere Worker-Instanzen parallel ansteuern.

**Strategien**:
- `least_loaded` (default) — Worker mit wenigster aktueller Last
- `round_robin` — zyklische Verteilung
- `random` — zufällige Auswahl

**Heartbeat-Überwachung**: Worker, die > 30s keinen Heartbeat
gesendet haben, werden als `down` markiert und nicht mehr
ausgewählt.

**Konfiguration**:
```env
WORKER_COUNT=2               # Anzahl paralleler Worker
WORKER_BASE_PORT=8771        # Worker :8771, :8772, ...
LOADBALANCER_STRATEGY=least_loaded
```

---

## 6. Shutdown

### Manuell

```bash
# Im Terminal: Ctrl+C
# Oder via MCP/ZMQ:
{
  "jsonrpc": "2.0", "id": 1, "method": "tools/call",
  "params": {
    "name": "shutdown",
    "arguments": {"api_key": "<API_KEY>"}
  }
}
```

### Reihenfolge (graceful)

1. HTTP-Server: kein neuer Request
2. WSSP-15: Heartbeat gestoppt
3. ZMQ-Hauptservice: keine neuen Requests
4. ZMQ-Loadbalancer: gestoppt
5. Worker-Pool: alle Worker gestoppt
6. Event-Loop: beendet

---

## 7. Health-Checks

| Was | Wie | Wann |
|---|---|---|
| Service-Health | `GET /api/health` | bei Bedarf |
| Worker-Health | Heartbeat alle 30s | automatisch |
| ZMQ-Health | `ping` / `get_manifest` | bei Bedarf |
| Framie-Health | SSE-Stream aktiv? | automatisch (Browser) |

---

## 8. Deployment

### Standalone (Entwicklung)

```bash
python main.py
```

### Docker

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY . .
RUN pip install -r requirements.txt
EXPOSE 8770 5570 5571 5690
CMD ["python", "main.py", "--no-browser"]
```

### Systemd (Linux)

```ini
[Unit]
Description=ME4-YouTube Service
After=network.target

[Service]
Type=simple
User=me4
WorkingDirectory=/opt/me4-youtube
ExecStart=/opt/me4-youtube/.venv/bin/python main.py --no-browser
Restart=always

[Install]
WantedBy=multi-user.target
```

---

## 9. Troubleshooting

| Problem | Ursache | Lösung |
|---|---|---|
| Port 8770 belegt | anderer Service | `--port 8888` |
| Framie öffnet nicht | Browser-Headless | `--no-browser` + manuell öffnen |
| Worker-Pool startet nicht | Port-Range zu klein | `WORKER_BASE_PORT` + `WORKER_COUNT` anpassen |
| ZMQ bind-Fehler | Port doppelt vergeben | anderen Port setzen |
| SM-Producer nicht erreichbar | `SM_PRODUCER_URL` falsch | URL prüfen, `SM_PRODUCER_ENABLED=false` zum Ignorieren |
| Auth-Fehler | `API_KEY` falsch | prüfen: `.env` vs. Aufruf |
