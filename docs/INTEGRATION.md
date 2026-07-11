# INTEGRATION.md — UI↔Service-Vertrag (Service-Perspektive)

> **Spiegelbildliche Doku.** Diese Datei dokumentiert den Vertrag aus Sicht **dieses Services** (`ME4-S-youtube`) gegenüber dem `ME4-UI`-Baustein. Die spiegelbildliche Sicht aus Baustein-Perspektive liegt in `D:\DEV\ME4-UI\docs\INTEGRATION.md` — bei Drift MUSS diese Datei aktualisiert werden.
> **Verbindlich:** `D:\Entwicklung\ME4-SERVICE-BUS-PILOT.md` Sektion 0.5.5.

## 1. Wer ruft mich an?

```
ME4-UI Baustein  ──HTTP POST──►  ME4-YouTube HTTP-API (:8770)
                ──ZMQ REQ────►  ME4-YouTube ZMQ-Main (:5570)
                ──ZMQ REQ────►  ME4-YouTube ZMQ-Loadbalancer (:5571) → Worker-Pool
                ──stdio─────►  ME4-YouTube MCP-Server (python main.py --mcp-stdio)
```

**Wir liefern /api/manifest**, der Baustein liest es einmal beim `POST /api/services/activate`.

## 2. Was wir liefern MÜSSEN — Pflichtfelder im `/api/manifest`

| Feld | Wert | Pflicht |
|---|---|---|
| `id` | `"ME4-YOUTUBE"` | ✅ |
| `name` | `"ME4-YouTube"` | ✅ |
| `apiProxyBase` | `"http://localhost:8770"` | ✅ (aus `app/config.py`) |
| `version` | `"1.0.0"` | ✅ |
| `kind` | `"service"` | ✅ (ab v1.0) |
| `greeting` | siehe `app/http_api.py:142` | ✅ |
| `pipeline[]` | 10 Stages | ✅ |
| `functions[]` | 6 Funktionen (Slots 0–5) | ✅ |
| `buttons[]` | **Genau 10** (Slots 0–9) | ✅ |
| `capabilities[]` | siehe unten | ✅ |
| `health_endpoint` | `"http://localhost:8770/api/health"` | ✅ |
| `subtitle`, `description` | empfohlen | SHOULD |
| `mcp{}`, `loadbalancer{}`, `ports{}`, `framie_endpoint` | optional | MAY |

**Capabilities (gemäß Implementierung):**
```
video_download, metadata_extraction, transcript_extraction,
comments_extraction, translation, load_balancing,
live_status_stream, sm_producer_integration
```

## 3. Slot-Konvention (unsere Belegung)

| Slot | Label | Function | Target | Status |
|---:|---|---|---|:---:|
| 0 | Get Metadata | `metadata` | `POST /api/metadata` | ✅ aktiv |
| 1 | Get Transcript | `transcript` | `POST /api/transcript` | ✅ aktiv |
| 2 | Get Comments | `comments` | `POST /api/comments` | ✅ aktiv |
| 3 | Download | `download` | `POST /api/download` | ✅ aktiv |
| 4 | Process | `process` | `POST /api/process` | ✅ aktiv |
| 5 | Trigger SM-Producer | `smproducer` | `POST /api/sm-produce` | ✅ aktiv |
| 6 | Ask PI-Agent | (UI-special) | `POST /__pi_agent__` | ⚠️ wird lokal abgefangen |
| 7 | Open Notes | (TODO) | `GET /notes/export` | ❌ 404 |
| 8 | Open Log | (TODO) | `GET /log/recent` | ❌ 404 |
| 9 | Reset Session | (TODO) | `POST /session/reset` | ❌ 404 |

> **TODO Phase 5:** Slots 7–9 entweder als Stub-Routen (`{"status":"not_implemented"}`) ergänzen oder aus dem Manifest entfernen. Slot 6 (`/__pi_agent__`) ist im UI-Reserved-Set und wird dort abgefangen, nicht an uns weitergeleitet — siehe `D:\DEV\ME4-UI\docs\INTEGRATION.md` §2.4.

## 4. Was wir bei Button-Klicks zurückgeben MÜSSEN

### 4.1 Standard-Response-Shape (Top-Level, kein Wrapper)

Bei Button-Klicks liefern wir unsere Felder **direkt auf Top-Level** —
**ohne** `_summary`-Wrapper. Das folgt der Industrie-Konvention (Google
API Design Guide, Stripe API, GitHub API, OpenAPI Resource Style). Die
UI ist tolerant gegenüber beiden Formen.

**Live-Beispiel** (curl gegen den laufenden Service):
```json
{
  "filesSavedTo": "data/sessions/abc123/01-get-metadata",
  "jsonPath":     "data/sessions/abc123/01-get-metadata/result.json",
  "mdPath":       "data/sessions/abc123/01-get-metadata/result.md",
  "headline":     { "success": true, "title": "Me at the zoo", "channel": "jawed" },
  "function":     "get-metadata"
}
```

**Pflichtfelder:**
- `headline.success` (bool)
- `headline` (object) — UI rendert das als Card-Header
- `function` (string) — Funktions-ID (z.B. `get-metadata`, `get-transcript`, `process`)
- `filesSavedTo` (string) — Pfad zum Ergebnis-Verzeichnis

**Optional:** `jsonPath`, `mdPath`, `download_path`, `_persistence`,
sowie beliebige **servicespezifische** Felder (z.B. `transcript_segments`,
`comments_count` bei `process`). Diese sind dokumentations-pflichtig
in `FUNCTIONS.md` §3.

**Implementierungs-Anker** (`app/http_api.py`):
- Z. 285 (`/api/metadata`) → Aufruf von `_summary("get-metadata", result)` Z. 300
- Z. 302 (`/api/transcript`) → Aufruf Z. 327
- Z. 328 (`/api/comments`) → Aufruf Z. 352
- Z. 370 (`/api/download`) → Aufruf Z. 391
- Z. 400 (`/api/process`) → nutzt Worker-Pool, ruft `_summary` indirekt
- Z. 405 (`/api/sm-produce`) → Aufruf Z. 415

Die Builder-Funktion `_summary(function_name, result)` in Z. 77 ist die
Single Source of Truth für dieses Schema — **alle** Endpoints gehen
durch sie.

**Wichtig für 20+ Services:** Wenn neue Services dazukommen, MÜSSEN sie
denselben Top-Level-Shape liefern. Siehe Pilot `D:\Entwicklung\ME4-SERVICE-BUS-PILOT.md`
Sektion 0.9 (ADR-001) für die Begründung gegen einen Wrapper.

### 4.2 `awaitInput` bei fehlenden Pflichtfeldern

Statt HTTP 400 liefern wir bei fehlender URL ein `awaitInput`-Envelope (siehe `FUNCTIONS.md` §3.1 Beispiel).

**Implementierung:** Pydantic-Validator in `app/models.py` mit `@field_validator("url")` löst `InvalidURLError` aus → HTTP-Layer übersetzt zu `awaitInput`.

### 4.3 Fehler-Codes

| Status | Bedeutung | Beispiel |
|---|---|---|
| 200 + Top-Level-Felder | Erfolg (mit `headline.success: true`) | — |
| 200 + `awaitInput` | Pflichtfeld fehlt | URL nicht angegeben |
| 400 | Validation-Error | `"Keine gueltige YouTube-URL"` |
| 401/403 | Auth-Fehler | API-Key falsch oder fehlt |
| 500 | Internal Server Error | yt-dlp-Exception |
| 502 | Upstream nicht erreichbar | SM-Producer down |
| 503 | Service nicht verfügbar | `--no-workers` Modus |

### 4.4 Persistenz-Konvention (siehe UI §5)

```
data/sessions/<sid>/<NN-function>/
├── result.json     ← Pflicht
├── result.md       ← Empfohlen
└── result.html     ← Optional
```

**Implementierung:** `app/worker.py` schreibt nach `process`-Abschluss. Wir nutzen `<sid>` aus dem Request (vom UI vorgegeben).

## 5. Auth-Drift (TODO Phase 5)

**Aktueller Zustand:** Wir setzen `API_KEY` in `.env`. Der UI-Baustein reicht diesen Key **nicht** an uns durch (siehe `D:\DEV\ME4-UI\docs\INTEGRATION.md` §4). **Konsequenz:** UI-Aufrufe scheitern mit 401, sobald `API_KEY != ""`.

**Workaround bis Phase 5:**
- `API_KEY=*** in `.env` lassen für UI-Tests
- Für externe Tools (curl, Agent Zero) → Key im Header mitsetzen

**Plan:** Per-Service `apiKey`-Override in `services/example-me4-youtube.service.json` + UI-Proxy-Update.

## 6. Stage-Update-Mechanik (aus UI-Sicht)

Der Baustein erwartet nach erfolgreichem Klick, dass wir mindestens eines liefern:
- `headline.success = true` (Top-Level) → alle Stages in `btn.function` werden auf `ok` gesetzt
- `_persistence.id` + `_persistence.json_path` (Top-Level) → UI kann Session-Datei referenzieren
- Bei `produces.kind="download"`: zusätzlich `file`-Feld (Top-Level) mit Pfad in `DOWNLOAD_DIR`

Wir liefern das aktuell konsistent in `process` (Worker-Pool). Die anderen Slots (0–5) liefern ebenfalls Top-Level-Felder mit `headline.success`, aber **ohne** `file`-Feld — UI behandelt das als OK ohne Download-Check.

## 7. Was der Baustein von uns NICHT erwartet

- **Eigenes Auth-Handling**: Wir sind der einzige Auth-Verantwortliche (HMAC-compare in `app/auth.py:23`)
- **Push-Notifications**: UI pollt, wir pushen nicht (außer SSE-Stream für Framie, separat)
- **CORS-Header**: UI fetcht vom gleichen Origin-Loopback, keine CORS-Issues
- **Rate-Limiting**: Aktuell nicht implementiert (TODO)

## 8. Implementierungs-Anker in unserem Code

| Vertrag-Element | Datei:Zeile |
|---|---|
| `/api/manifest` Route | `app/http_api.py:142` |
| `/api/process` Route (Worker-Pool) | `app/http_api.py:170` |
| `_summary` Builder (Top-Level-Response) | `app/http_api.py:77` |
| `awaitInput` für fehlende URL | `app/models.py` (`@field_validator("url")`) |
| Auth HMAC-compare | `app/auth.py:23` |
| ZMQ-Main Service | `app/zmq_service.py` |
| Loadbalancer-MCP | `app/loadbalancer.py:135` |
| Worker-Sub-Prozess | `app/worker.py` |
| Framie-SSE | `app/http_api.py:150` |

## 9. Schwester-Dateien

- **Baustein-Seite (ME4-UI):** `D:\DEV\ME4-UI\docs\INTEGRATION.md`
- **Pilot-Standard:** `D:\Entwicklung\ME4-SERVICE-BUS-PILOT.md` Sektion 0.5.5

Bei Widersprüchen MUSS die hier stehende (unsere) Version per PR aktualisiert werden, mit `CHANGELOG.md`-Eintrag `BREAKING:`.