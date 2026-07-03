"""AdFlow MCP Streamable HTTP — mount on FastAPI at /mcp (Hermes remote URL)."""

from __future__ import annotations

import importlib.util
import os
import sys
from typing import Any

from starlette.applications import Starlette

from src.config import ROOT

_MCP_MODULE: Any | None = None
_MCP_INSTANCE: Any | None = None
_MCP_HTTP_APP: Starlette | None = None


def _default_adflow_base_url() -> str:
    port = os.environ.get("WEBHOOK_PORT") or os.environ.get("PORT") or "8787"
    return f"http://127.0.0.1:{port}"


def _load_mcp_module() -> Any:
    global _MCP_MODULE
    if _MCP_MODULE is not None:
        return _MCP_MODULE
    path = ROOT / "mcp_server" / "server.py"
    spec = importlib.util.spec_from_file_location("adflow_mcp_server", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load MCP server from {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["adflow_mcp_server"] = mod
    spec.loader.exec_module(mod)
    _MCP_MODULE = mod
    return mod


def init_mcp_http() -> tuple[Any, Starlette]:
    """Load MCP tools module and build Streamable HTTP ASGI app (path /mcp)."""
    global _MCP_INSTANCE, _MCP_HTTP_APP
    if _MCP_HTTP_APP is not None and _MCP_INSTANCE is not None:
        return _MCP_INSTANCE, _MCP_HTTP_APP
    os.environ.setdefault("ADFLOW_BASE_URL", _default_adflow_base_url())
    mod = _load_mcp_module()
    _MCP_INSTANCE = mod.mcp
    _MCP_HTTP_APP = _MCP_INSTANCE.streamable_http_app()
    return _MCP_INSTANCE, _MCP_HTTP_APP
