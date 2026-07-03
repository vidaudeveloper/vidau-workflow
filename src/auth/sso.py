"""VidAU SSO — SDK 配置与服务端 token 校验。"""

from __future__ import annotations

from typing import Any

import httpx

from src.config import Settings, get_settings


class SsoError(Exception):
    def __init__(self, message: str, *, code: int | None = None):
        super().__init__(message)
        self.code = code


def sso_enabled(settings: Settings | None = None) -> bool:
    settings = settings or get_settings()
    if (settings.auth_mode or "local").lower() != "platform":
        return False
    return bool((settings.sso_app_id or "").strip())


def _host_from_settings(settings: Settings) -> str:
    raw = (settings.app_domain or settings.public_base_url or "").strip().lower()
    if "://" in raw:
        raw = raw.split("://", 1)[1]
    return raw.split("/", 1)[0].split(":", 1)[0].strip(".")


def _detect_env(settings: Settings) -> str:
    host = _host_from_settings(settings)
    if not host:
        return "production"
    if "vidau.info" in host:
        return "development"
    if "vidau.ai" in host:
        return "production"
    return "production"


_SSO_ENV_ALIASES = {
    "production": "production",
    "prod": "production",
    "development": "development",
    "dev": "development",
    "test": "development",
    "staging": "development",
}


def sso_env_name(settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    explicit = (settings.sso_env or "").strip().lower()
    if explicit in _SSO_ENV_ALIASES:
        return _SSO_ENV_ALIASES[explicit]
    return _detect_env(settings)


def sso_base_url(settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    override = (settings.sso_base_url or "").strip().rstrip("/")
    if override:
        return override
    if sso_env_name(settings) == "development":
        return "https://sso.vidau.info"
    return "https://sso.vidau.ai"


def sso_sdk_url(settings: Settings | None = None) -> str:
    return f"{sso_base_url(settings)}/sdk/vidau-sso.min.js"


def sso_disabled_reason(settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    mode = (settings.auth_mode or "local").lower()
    if mode != "platform":
        return f"AUTH_MODE 不是 platform（当前: {settings.auth_mode or 'local'}）"
    if not (settings.sso_app_id or "").strip():
        return "SSO_APP_ID 未配置"
    return ""


def sso_public_config(settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    enabled = sso_enabled(settings)
    base = sso_base_url(settings) if enabled else ""
    reason = "" if enabled else sso_disabled_reason(settings)
    return {
        "enabled": enabled,
        "app_id": (settings.sso_app_id or "").strip() if enabled else "",
        "sdk_url": sso_sdk_url(settings) if enabled else "",
        "env": sso_env_name(settings) if enabled else "",
        "base_url": base,
        "user_info_url": f"{base}/api/sso/user-info" if base else "",
        "disabled_reason": reason,
        "auth_mode": (settings.auth_mode or "local").lower(),
        "auth_enabled": bool(settings.auth_enabled),
    }


async def verify_sso_token(token: str, settings: Settings | None = None) -> dict[str, Any]:
    """与 SSO SDK 一致：POST {sso}/api/sso/user-info，Token 走 Header。"""
    settings = settings or get_settings()
    raw = token.strip()
    if not raw:
        raise SsoError("缺少 token")
    url = f"{sso_base_url(settings)}/api/sso/user-info"
    headers = {
        "X-Token": raw,
        "Token": raw,
        "Authorization": raw,
    }
    try:
        async with httpx.AsyncClient(timeout=30.0) as cli:
            resp = await cli.post(url, json={}, headers=headers)
    except httpx.HTTPError as exc:
        raise SsoError(f"SSO 校验请求失败: {exc}") from exc
    try:
        payload = resp.json()
    except ValueError as exc:
        raise SsoError("SSO 返回非 JSON") from exc
    code = payload.get("code")
    if code not in (None, 0):
        raise SsoError(
            str(payload.get("msg") or payload.get("message") or f"SSO code={code}"),
            code=code if isinstance(code, int) else None,
        )
    data = payload.get("data")
    if not isinstance(data, dict):
        raise SsoError("SSO 未返回用户信息")
    inner_code = data.get("code")
    if inner_code not in (None, 0):
        raise SsoError(
            str(data.get("message") or data.get("msg") or f"SSO data code={inner_code}"),
            code=inner_code if isinstance(inner_code, int) else None,
        )
    user = data.get("user") if isinstance(data.get("user"), dict) else data
    result = dict(data)
    if isinstance(user, dict):
        result["user"] = user
    return result


def sso_user_from_verify(data: dict[str, Any]) -> dict[str, Any]:
    user = data.get("user")
    return user if isinstance(user, dict) else {}


def profile_from_sso_user(user: dict[str, Any]):
    """将 SSO verify-token 的 user 转为 UserProfile。"""
    from src.platform.client import UserProfile

    if not user:
        return None
    uid = str(user.get("id") or user.get("userId") or user.get("user_id") or "")
    if not uid:
        return None
    return UserProfile(
        user_id=uid,
        nickname=str(user.get("nickname") or user.get("nickName") or user.get("email") or uid),
        email=str(user.get("email") or ""),
        avatar=str(user.get("avatar") or ""),
    )
