"""VidAU Agent 套餐购买 — 跳转主站 agent-price 页。"""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Any
from urllib.parse import urlencode

from src.config import ROOT, Settings, get_settings
from src.platform.billing import billing_enabled

_PRICING_FILE = ROOT / "config" / "agent_pricing.json"


@lru_cache
def load_agent_pricing() -> dict[str, Any]:
    if not _PRICING_FILE.is_file():
        return {}
    try:
        return json.loads(_PRICING_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def agent_purchase_url(settings: Settings | None = None, *, agent_code: str = "") -> str:
    settings = settings or get_settings()
    base = (settings.agent_purchase_base_url or "https://www.vidau.ai/agent-price").rstrip("/")
    code = (agent_code or settings.agent_code or settings.sso_app_id or "").strip()
    if not code:
        return base
    return f"{base}?{urlencode({'agent_code': code})}"


def billing_public_meta(settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    pricing = load_agent_pricing()
    agent_code = (
        (settings.agent_code or "").strip()
        or (settings.sso_app_id or "").strip()
        or str(pricing.get("agent_code") or "")
    )
    enabled = billing_enabled(settings) or (settings.auth_mode or "").lower() == "platform"
    return {
        "enabled": enabled,
        "charge_enabled": billing_enabled(settings),
        "billing_mode": (settings.aigc_billing_mode or "none").lower(),
        "agent_code": agent_code,
        "purchase_url": agent_purchase_url(settings, agent_code=agent_code),
        "agent_name": pricing.get("agent_name", "VidAU Flow"),
        "agent_name_en": pricing.get("agent_name_en", "VidAU Flow"),
        "tagline": pricing.get("tagline", ""),
        "pricing_note": pricing.get("pricing_note", ""),
        "features": pricing.get("features", []),
        "packages": pricing.get("packages", []),
        "coin_usage": pricing.get("coin_usage", []),
    }
