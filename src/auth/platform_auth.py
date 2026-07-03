"""VidAU 主站 Token 鉴权 — 对齐 vidau-agent middleware.ts。

Token 来源（严格分离）：
- 开发（auth_dev_fallback / 非 HTTPS 本地）：URL ?token= 或 Cookie/Header dev-token
- 生产：Cookie VidAu-Token（同域主站登录自动带入）

userId：用 token 调主站 getUserInfo，不解析 JWT（token 会轮换）。
带内存缓存 token→userId，TTL = auth_user_cache_ttl_ms。
"""

from __future__ import annotations

import base64
import json
import time

from fastapi import Request

from src.config import Settings, get_settings
from src.platform.client import PlatformError, UserProfile, get_platform_client

# token -> (userId, expire_epoch)
_USER_ID_CACHE: dict[str, tuple[str, float]] = {}
# token -> (UserProfile, expire_epoch)；getUserInfo 完整结果短缓存，供积分展示
_PROFILE_CACHE: dict[str, tuple[UserProfile, float]] = {}
# 最近一次成功解析的 profile；getUserInfo 偶发失败时避免误踢登录
_STALE_PROFILE: dict[str, UserProfile] = {}


def _now() -> float:
    return time.time()


def _cache_get(cache: dict, token: str):
    item = cache.get(token)
    if not item:
        return None
    value, exp = item
    if exp < _now():
        cache.pop(token, None)
        return None
    return value


def _cache_set(cache: dict, token: str, value, ttl_ms: int) -> None:
    cache[token] = (value, _now() + max(1, ttl_ms) / 1000.0)


def extract_token(request: Request, settings: Settings | None = None) -> str:
    """按环境取 token（Cookie → Header token/X-Token → Flow session）。"""
    settings = settings or get_settings()
    cookies = request.cookies
    if not settings.auth_flow_session_only:
        prod_token = cookies.get(settings.platform_token_cookie)
        if prod_token:
            return prod_token.strip()
    for header in ("token", "X-Token", "x-token"):
        header_token = request.headers.get(header)
        if header_token:
            return header_token.strip()
    dev_cookie = cookies.get(settings.platform_dev_token_cookie)
    if dev_cookie:
        return dev_cookie.strip()
    header_token = request.headers.get("x-vidau-dev-token")
    if header_token:
        return header_token.strip()
    url_token = request.query_params.get("token")
    if url_token:
        return url_token.strip()
    return ""


def _decode_jwt_user_id(token: str) -> str:
    """仅开发兜底：从 JWT payload 解析 userId（不验签）。"""
    try:
        parts = token.split(".")
        if len(parts) < 2:
            return ""
        payload_b64 = parts[1] + "=" * (-len(parts[1]) % 4)
        data = json.loads(base64.urlsafe_b64decode(payload_b64).decode("utf-8"))
    except Exception:  # noqa: BLE001
        return ""
    for key in ("userId", "user_id", "sub", "id"):
        val = data.get(key)
        if val is not None and str(val).strip():
            return str(val).strip()
    return ""


async def resolve_user_id(token: str, settings: Settings | None = None) -> str:
    """token → 主站 userId（带缓存）；失败返回空串。"""
    settings = settings or get_settings()
    if not token:
        return ""
    cached = _cache_get(_USER_ID_CACHE, token)
    if cached:
        return cached
    try:
        profile = await get_platform_client().get_user_info(token)
    except PlatformError:
        if settings.auth_dev_fallback:
            uid = _decode_jwt_user_id(token)
            if uid:
                _cache_set(_USER_ID_CACHE, token, uid, settings.auth_user_cache_ttl_ms)
            return uid
        return ""
    _cache_set(_USER_ID_CACHE, token, profile.user_id, settings.auth_user_cache_ttl_ms)
    _cache_set(_PROFILE_CACHE, token, profile, settings.auth_user_cache_ttl_ms)
    return profile.user_id


def cache_platform_profile(token: str, profile: UserProfile, settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    _cache_set(_USER_ID_CACHE, token, profile.user_id, settings.auth_user_cache_ttl_ms)
    _cache_set(_PROFILE_CACHE, token, profile, settings.auth_user_cache_ttl_ms)


async def resolve_profile(token: str, settings: Settings | None = None) -> UserProfile | None:
    """token → 完整 UserProfile（含积分），带短缓存。"""
    settings = settings or get_settings()
    if not token:
        return None
    cached = _cache_get(_PROFILE_CACHE, token)
    if cached:
        return cached
    profile: UserProfile | None = None
    try:
        profile = await get_platform_client().get_user_info(token)
    except PlatformError:
        uid = _decode_jwt_user_id(token)
        if uid:
            profile = UserProfile(user_id=uid, nickname=uid)
    if profile:
        cache_platform_profile(token, profile, settings)
        _STALE_PROFILE[token] = profile
        return profile
    stale = _STALE_PROFILE.get(token)
    if stale:
        return stale
    return None


def clear_cache() -> None:
    _USER_ID_CACHE.clear()
    _PROFILE_CACHE.clear()
    _STALE_PROFILE.clear()
