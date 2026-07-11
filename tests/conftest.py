"""Pytest-Konfiguration: stellt Pfad + Test-Settings bereit."""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Projekt-Root zu sys.path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Test-Isolation: eigene .env nicht laden, Defaults nutzen
os.environ.setdefault("API_KEY", "test-key")
os.environ.setdefault("WORKER_COUNT", "1")
os.environ.setdefault("HTTP_PORT", "0")  # Random
os.environ.setdefault("ZMQ_PORT", "0")
os.environ.setdefault("LOADBALANCER_ZMQ_PORT", "0")
os.environ.setdefault("SM_PRODUCER_ENABLED", "false")
os.environ.setdefault("LOG_LEVEL", "WARNING")
