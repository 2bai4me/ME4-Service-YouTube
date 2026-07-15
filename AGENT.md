# AGENT.md — ME4-YouTube

> **Service-ID:** `ME4-YOUTUBE`  
> **Version:** `1.2.001`
> **Schnittstellen:** MCP (stdio + ZMQ REQ/REP) + HTTP/REST + Framie-UI  
> **ZMQ Port Main:** `5570`  
> **ZMQ Port Loadbalancer:** `5571`  
> **Web Port:** `8770`

---

## Schnellstart für Agenten

```bash
# Service starten (alle Layer + Framie im Browser)
python main.py

# Nur als MCP-Server (stdio) — für Claude Code / Agenten ohne ZMQ
python main.py --mcp-stdio
```

---

## 1. MCP via stdio (empfohlen für Agenten)

### Starten

```bash
python main.py --mcp-stdio
```

### Tools

| Tool | Auth | Beschreibung |
|---|---|---|
| `ping` | public | Service-Health |
| `get_manifest` | public | UI-Manifest für Cockpit |
| `health` | public | Detaillierter Status inkl. Pool |
| `get_metadata` | 🔑 | YouTube Metadaten + Description |
| `get_transcript` | 🔑 | YouTube Transkript |
| `get_comments` | 🔑 | YouTube Top-Kommentare |
| `download` | 🔑 | Video/Audio herunterladen |
| `process` | 🔑 | Komplette Pipeline (alle 4 Features) |
| `trigger_sm_produce` | 🔑 | SM-Producer triggern |
| `shutdown` | 🔑 | Service herunterfahren |

### Beispiel: `process` (komplette YouTube-Pipeline)

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/call",
  "params": {
    "name": "process",
    "arguments": {
      "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
      "download": false,
      "include_description": true,
      "include_transcript": true,
      "include_comments": true,
      "language": "de",
      "max_comments": 100,
      "api_key": "ob-youtube-key-2026"
    }
  }
}
```

### Beispiel: `get_metadata` (nur Beschreibung)

```json
{
  "jsonrpc": "2.0",
  "id": 2,
  "method": "tools/call",
  "params": {
    "name": "get_metadata",
    "arguments": {
      "url": "https://youtu.be/dQw4w9WgXcQ",
      "api_key": "ob-youtube-key-2026"
    }
  }
}
```

### Authentifizierung

Wenn `API_KEY` in `.env` gesetzt ist, MÜSSEN alle geschützten Tools
`api_key` im `arguments`-Objekt übergeben.

```python
"arguments": {
    "url": "...",
    "api_key": "<API_KEY>"
}
```

---

## 2. ZMQ REQ/REP (für hochperformante Agent→Service-Kommunikation)

```python
import zmq, json

ctx = zmq.Context()
sock = ctx.socket(zmq.REQ)
sock.connect("tcp://127.0.0.1:5570")
sock.setsockopt(zmq.RCVTIMEO, 30000)

sock.send_json({
    "jsonrpc": "2.0", "id": "1", "method": "tools/call",
    "params": {"name": "process", "arguments": {
        "url": "https://youtu.be/dQw4w9WgXcQ",
        "api_key": "ob-youtube-key-2026",
    }}
})
print(json.dumps(sock.recv_json(), indent=2, ensure_ascii=False))
```

### Loadbalancer-MCP (parallele Verarbeitung)

```python
sock.connect("tcp://127.0.0.1:5571")  # Loadbalancer statt Main
# gleiches JSON-RPC-Protokoll — der Loadbalancer verteilt auf Worker
```

---

## 3. HTTP (für externe Tools / Browser)

```bash
curl -X POST http://localhost:8770/api/process \
  -H "X-API-Key: ob-youtube-key-2026" \
  -H "Content-Type: application/json" \
  -d '{"url":"https://youtu.be/dQw4w9WgXcQ"}'
```

Header: `X-API-Key: <API_KEY>`

---

## 4. Shutdown

- via MCP/ZMQ: Tool `shutdown` (mit `api_key`)
- via HTTP: nicht vorgesehen (MCP-only)
- `Ctrl+C` im Terminal

---

## Wichtige Code-Pfade

### YouTube-URL parsen
```python
from app.extractor import extract_video_id
vid = extract_video_id("https://youtu.be/dQw4w9WgXcQ")  # → "dQw4w9WgXcQ"
```

### Komplett-Verarbeitung
```python
from app.models import ProcessRequest
from app.orchestrator import Orchestrator

req = ProcessRequest(url="https://youtu.be/...", download=True)
orch = Orchestrator(worker_id="agent-1")
result = await orch.process(req)
```

### Loadbalancer benutzen
```python
import zmq
sock = zmq.Context().socket(zmq.REQ)
sock.connect("tcp://127.0.0.1:5571")
sock.send_json({
    "jsonrpc": "2.0", "id": 1, "method": "tools/call",
    "params": {"name": "process", "arguments": {...}}
})
```

---

## Antwort-Format

MCP-Standard:
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "content": [{"type": "text", "text": "{...}"}]
  }
}
```

Das `text`-Feld enthält das eigentliche Ergebnis als JSON-String.
Parse mit `json.loads(result["content"][0]["text"])`.

---

## Dependencies

- `yt-dlp` — YouTube Video-/Metadata-Extraktion
- `youtube-transcript-api` — Transkripte
- `pyzmq` — ZMQ-Kommunikation
- `fastapi` + `uvicorn` — HTTP-API
- `httpx` — SM-Producer Anbindung
- `pydantic` — Input-Validierung

Optional:
- `ffmpeg` — für Audio-Konvertierung
