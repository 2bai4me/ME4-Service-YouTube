# SM-Producer Integration

> Anbindung des `ME4-YouTube`-Services an die `ME4-SMproducer-3`-Pipeline.

---

## Übersicht

```
┌─────────────────────┐       ┌──────────────────────┐
│   ME4-YouTube       │       │  ME4-SMproducer-3    │
│   (Service)         │       │  (Pipeline :3001)    │
│                     │       │                      │
│  ┌───────────────┐  │ POST  │  ┌────────────────┐  │
│  │ /api/sm-      │──┼──────►│  │ /api/sm-       │  │
│  │  produce      │  │       │  │  produce       │  │
│  │ (X-API-Key)   │  │       │  │                │  │
│  └───────────────┘  │       │  └────────────────┘  │
│                     │       │                      │
│  ┌───────────────┐  │ GET   │  ┌────────────────┐  │
│  │ /api/health   │──┼──────►│  │ /api/health    │  │
│  │ (check)       │  │       │  │                │  │
│  └───────────────┘  │       │  └────────────────┘  │
│                     │       │                      │
│  ┌───────────────┐  │       │  ┌────────────────┐  │
│  │ trigger_sm_   │  │       │  │  Pipeline:     │  │
│  │ produce (ZMQ) │  │       │  │  → Renderer    │  │
│  └───────────────┘  │       │  │  → Transkript  │  │
│                     │       │  │  → Speech-Spl. │  │
│                     │       │  │  → TTS         │  │
└─────────────────────┘       │  │  → NotebookLM  │  │
                              │  └────────────────┘  │
                              └──────────────────────┘
```

---

## Konfiguration

In `ME4-YouTube/.env`:

```env
SM_PRODUCER_URL=http://localhost:3001
SM_PRODUCER_API_KEY=ob-dev-key-2026
SM_PRODUCER_ENABLED=true
```

Beim Service-Start wird `GET {SM_PRODUCER_URL}/api/health` aufgerufen
(3s Timeout). Falls erreichbar:
```
SM-Producer erreichbar: http://localhost:3001
```
Falls nicht erreichbar:
```
SM-Producer nicht erreichbar (kann später starten): ...
```
**Der Service startet trotzdem** — die Anbindung ist optional aktivierbar.

---

## Verwendung

### Variante 1: HTTP-Endpoint

```bash
curl -X POST http://localhost:8770/api/sm-produce \
  -H "X-API-Key: <YOUR_API_KEY>" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://youtu.be/dQw4w9WgXcQ",
    "transcript": "Never gonna give you up...",
    "language": "de",
    "workflow": "default",
    "metadata": {"channel": "...", "title": "..."}
  }'
```

Weitergeleitet wird an:
```http
POST {SM_PRODUCER_URL}/api/sm-produce
X-API-Key: {SM_PRODUCER_API_KEY}
Content-Type: application/json

{
  "video_url": "https://youtu.be/dQw4w9WgXcQ",
  "transcript": "Never gonna give you up...",
  "language": "de",
  "workflow": "default",
  "metadata": {...},
  "source": "ME4-YouTube"
}
```

### Variante 2: MCP / ZMQ Tool

```python
import zmq, json

sock = zmq.Context().socket(zmq.REQ)
sock.connect("tcp://127.0.0.1:5570")
sock.send_json({
    "jsonrpc": "2.0", "id": 1, "method": "tools/call",
    "params": {
        "name": "trigger_sm_produce",
        "arguments": {
            "url": "https://youtu.be/dQw4w9WgXcQ",
            "transcript": "Never gonna give you up...",
            "language": "de",
            "workflow": "default",
            "api_key": "<YOUR_API_KEY>",
        }
    }
})
print(sock.recv_json())
```

### Variante 3: Komplett-Pipeline (`process` → SM-Produce)

Kombiniert YouTube-Extraktion + SM-Produce in einem Schritt
(allerdings muss SM-Produce manuell danach aufgerufen werden,
da der `process`-Endpoint die Daten zurückgibt).

---

## Beispiel: End-to-End

```python
import httpx

# 1. YouTube-Daten holen
r = httpx.post("http://localhost:8770/api/process", json={
    "url": "https://youtu.be/dQw4w9WgXcQ",
    "include_transcript": True,
    "include_description": True,
    "language": "de",
}, headers={"X-API-Key": "<YOUR_API_KEY>"})

data = r.json()
transcript_text = " ".join(s["text"] for s in data["transcript"]["snippets"])

# 2. An SM-Producer weiterleiten
r = httpx.post("http://localhost:8770/api/sm-produce", json={
    "url": data["url"],
    "transcript": transcript_text,
    "language": "de",
    "workflow": "youtube-to-short",
    "metadata": data["metadata"],
}, headers={"X-API-Key": "<YOUR_API_KEY>"})

print("Pipeline gestartet:", r.json())
```

---

## Fehlerbehandlung

| HTTP-Status | Bedeutung | Ursache |
|---|---|---|
| 200 | OK | Erfolgreich weitergeleitet |
| 502 | Bad Gateway | SM-Producer nicht erreichbar |
| 401 | Unauthorized | API-Key fehlt/falsch |
| 500 | Server Error | Siehe Service-Log |

---

## Status-Tracking

Im Framie-Stream sieht man:
- Job-Erstellung
- Step-Transitions (metadata → transcript → comments → done)
- Worker-ID
- Dauer

SM-Produce-Aufrufe sind NICHT Teil des Job-Status-Trackers (sie sind
Fire-and-Forget). Der Erfolg wird im Service-Log festgehalten.

---

## Nächste Schritte

- Bidirektionale Integration: Webhook von SM-Producer → Status-Update
- Bidirektionale Integration: SM-Producer ruft `get_metadata` direkt
- Bidirektionale Integration: Service-Status in SM-Producer-Cockpit
