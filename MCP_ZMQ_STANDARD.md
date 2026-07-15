# MCP_ZMQ_STANDARD.md — Konformitätserklärung

> **Service:** `ME4-YouTube` (`ME4-YOUTUBE`)  
> **Status:** ✅ Voll konform zum [ME4 MCP+ZMQ Standard](D:/Entwicklung/ME4-Service-NotebookLM/MCP_ZMQ_STANDARD.md) v1.0

---

## Compliance-Übersicht

| Pflicht-Element | Status | Wo |
|---|---|---|
| ZMQ REQ/REP mit JSON-RPC 2.0 | ✅ | `app/zmq_service.py`, `app/loadbalancer.py` |
| API-Key Auth (X-API-Key / api_key) | ✅ | `app/auth.py` (HMAC-compare, constant-time) |
| UI-Manifest | ✅ | `zmq_service._manifest()` + `/api/manifest` |
| Service-ID | ✅ | `ME4-YOUTUBE` |
| API-Version | ✅ | `1.2.001` |
| Standard-Tools (`ping`, `get_manifest`, `health`, `shutdown`) | ✅ | `zmq_service._tools_list()` |
| `tools/list` & `tools/call` | ✅ | `zmq_service._handle()` |
| `SERVICE.md` & `AGENT.md` | ✅ | im Repo |
| Tests | ✅ | `tests/test_*.py` |

---

## Zusätzliche Schnittstellen (optional/konform)

| Schnittstelle | Zweck | Pflicht |
|---|---|---|
| HTTP / REST (Port 8770) | Browser, externe Tools | optional — ✅ implementiert |
| Loadbalancer-MCP (Port 5571) | parallele Worker | ✅ implementiert |
| MCP stdio | Agenten ohne ZMQ | ✅ implementiert |
| Framie-UI | Live-Status | ✅ implementiert |

---

## Tool-Liste (vollständig)

| Tool | Auth | Beschreibung |
|---|---|---|
| `ping` | public | Service-Health |
| `get_manifest` | public | UI-Manifest für Cockpit |
| `health` | public | Detaillierter Status inkl. Worker-Pool |
| `get_status_snapshot` | public | Live-Job-Status |
| `get_metadata` | 🔑 | YouTube Metadaten + Description |
| `get_transcript` | 🔑 | YouTube Transkript |
| `get_comments` | 🔑 | YouTube Top-Kommentare |
| `download` | 🔑 | Video/Audio herunterladen |
| `process` | 🔑 | Komplette Pipeline (alle 4 Features) |
| `trigger_sm_produce` | 🔑 | SM-Producer triggern |
| `shutdown` | 🔑 | Service herunterfahren |

---

## Loadbalancer-MCP

Der Service betreibt zusätzlich einen **Loadbalancer-MCP** auf Port 5571.
Dieser ist **Teil der Schnittstelle** (kein optionales Add-on) und
ermöglicht die parallele Ansteuerung mehrerer Worker-Instanzen.

Strategien: `round_robin` | `least_loaded` (default) | `random`

---

## Siehe auch

- [MCP_ZMQ_STANDARD.md](D:/Entwicklung/ME4-Service-NotebookLM/MCP_ZMQ_STANDARD.md) — verbindlicher Standard
- [SERVICE.md](./SERVICE.md) — Architektur & Endpunkte
- [AGENT.md](./AGENT.md) — Agenten-Anleitung
- [SERVICE_START.md](./SERVICE_START.md) — Boot-Sequenz & Lifecycle
