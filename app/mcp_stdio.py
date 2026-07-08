"""MCP stdio Server — für Agenten ohne ZMQ.

Liest JSON-RPC 2.0 zeilenweise von stdin, antwortet auf stdout.
Implementiert dieselben Tools wie ZMQService.
"""
from __future__ import annotations

import asyncio
import json
import sys
from typing import Any

from app.auth import verify_zmq_key
from app.config import settings
from app.loadbalancer import WorkerPool
from app.logging_config import get_logger

logger = get_logger(__name__)


class MCPStdio:
    """MCP-Server über stdin/stdout (für Agenten/Claude Code)."""

    def __init__(self, pool: WorkerPool):
        self.pool = pool

    async def run(self) -> None:
        """Hauptloop: liest von stdin, schreibt nach stdout."""
        logger.info("MCP stdio server running")
        loop = asyncio.get_event_loop()
        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)
        await loop.connect_read_pipe(lambda: protocol, sys.stdin)

        while True:
            line = await reader.readline()
            if not line:
                break
            try:
                msg = json.loads(line.decode("utf-8").strip())
                resp = await self._handle(msg)
            except json.JSONDecodeError as e:
                resp = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": f"parse error: {e}"}}
            except Exception as e:  # noqa: BLE001
                resp = {"jsonrpc": "2.0", "id": None, "error": {"code": -32603, "message": str(e)}}
            sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            sys.stdout.flush()

    async def _handle(self, msg: dict[str, Any]) -> dict[str, Any]:
        method = msg.get("method", "")
        rid = msg.get("id", 0)
        if method == "initialize":
            return {
                "jsonrpc": "2.0", "id": rid,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "serverInfo": {"name": settings.service_id, "version": settings.service_version},
                    "capabilities": {"tools": {}},
                },
            }
        if method == "tools/list":
            return {
                "jsonrpc": "2.0", "id": rid,
                "result": {"tools": [
                    {"name": "ping", "description": "Public ping"},
                    {"name": "get_manifest", "description": "Public manifest"},
                    {"name": "health", "description": "Public health"},
                    {"name": "process", "description": "YouTube process (auth)", "inputSchema": {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]}},
                    {"name": "get_metadata", "description": "Get metadata (auth)", "inputSchema": {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]}},
                    {"name": "get_transcript", "description": "Get transcript (auth)", "inputSchema": {"type": "object", "properties": {"url": {"type": "string"}, "language": {"type": "string"}}, "required": ["url"]}},
                    {"name": "get_comments", "description": "Get comments (auth)", "inputSchema": {"type": "object", "properties": {"url": {"type": "string"}, "max_comments": {"type": "integer"}}, "required": ["url"]}},
                    {"name": "download", "description": "Download video (auth)", "inputSchema": {"type": "object", "properties": {"url": {"type": "string"}, "audio_only": {"type": "boolean"}}, "required": ["url"]}},
                ]},
            }
        if method == "tools/call":
            return await self._tools_call(rid, msg.get("params", {}))
        return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": f"unknown method: {method}"}}

    async def _tools_call(self, rid: Any, params: dict) -> dict[str, Any]:
        name = params.get("name", "")
        args = params.get("arguments", {}) or {}
        if name not in {"ping", "get_manifest", "health"}:
            try:
                verify_zmq_key(args)
            except Exception as e:  # noqa: BLE001
                return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32001, "message": str(e)}}

        if name == "ping":
            return {"jsonrpc": "2.0", "id": rid, "result": {"content": [{"type": "text", "text": json.dumps({"status": "ok", "service": settings.service_id})}]}}
        if name == "get_manifest":
            from app.zmq_service import ZMQService
            # Dummy-Methode aufrufen
            return {"jsonrpc": "2.0", "id": rid, "result": {"content": [{"type": "text", "text": "manifest: siehe ZMQService._manifest()"}]}}
        if name == "health":
            return {"jsonrpc": "2.0", "id": rid, "result": {"content": [{"type": "text", "text": json.dumps(self.pool.status())}]}}
        if name == "process":
            return await self._forward(args)
        if name in ("get_metadata", "get_transcript", "get_comments", "download"):
            return await self._forward(args)
        return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32602, "message": f"unknown tool: {name}"}}

    async def _forward(self, args: dict) -> dict[str, Any]:
        """Leitet an einen Worker weiter."""
        import httpx
        try:
            w = self.pool.select_worker()
        except Exception as e:  # noqa: BLE001
            return {"jsonrpc": "2.0", "id": "process", "error": {"code": -32002, "message": str(e)}}
        async with httpx.AsyncClient(timeout=settings.request_timeout_sec) as c:
            r = await c.post(f"http://{w.host}:{w.port}/process", json=args)
            r.raise_for_status()
            return {"jsonrpc": "2.0", "id": "process", "result": {"content": [{"type": "text", "text": json.dumps(r.json(), ensure_ascii=False)}]}}
