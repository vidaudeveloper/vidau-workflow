"""Headless service entrypoint for the AdFlow backend.

Launched by the Windows scheduled task `AdFlowBackend` via pythonw.exe (so there
is no console window). Redirects stdout/stderr to data/logs/backend.log and
serves the FastAPI app on 127.0.0.1:8787 for the local Hermes MCP to call.

Run manually for a foreground test with:  python scripts/run_batch.py serve
"""

from __future__ import annotations

import os
import sys

# Always operate from the project root regardless of where the task launches us.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)

LOG_DIR = os.path.join(ROOT, "data", "logs")
os.makedirs(LOG_DIR, exist_ok=True)
_log = open(os.path.join(LOG_DIR, "backend.log"), "a", buffering=1, encoding="utf-8")
sys.stdout = _log
sys.stderr = _log

HOST = os.environ.get("ADFLOW_HOST", "127.0.0.1")
PORT = int(os.environ.get("ADFLOW_PORT", "8787"))

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("src.app:app", host=HOST, port=PORT)
