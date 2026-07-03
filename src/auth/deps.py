"""FastAPI 鉴权依赖。"""

from __future__ import annotations

from fastapi import HTTPException, Request

from src.config import get_settings
from src.db.repository import Repository

PUBLIC_PREFIXES = (
    "/health",
    "/login",
    "/hermes/",
    "/.well-known/",
    "/mcp",
    "/assets/",
    "/api/auth/",
    "/api/meta",
    "/api/canvas/",
    "/api/billing/",
    "/api/toc/locale",
    "/api/toc/config",
    "/api/toc/intake/formats",
)


def is_public_path(path: str) -> bool:
    if path == "/":
        return True
    return any(path.startswith(prefix) for prefix in PUBLIC_PREFIXES)


def get_session_user_id(request: Request) -> str | None:
    return request.session.get("user_id")


def is_platform_mode(settings=None) -> bool:
    settings = settings or get_settings()
    return (settings.auth_mode or "local").lower() == "platform"


def require_user(request: Request) -> dict:
    settings = get_settings()
    if not settings.auth_enabled:
        return {"id": "", "email": "", "display_name": "本地开发", "role": "admin"}
    # platform 模式：用户身份由 auth_guard middleware 解析后写入 request.state.user
    if is_platform_mode(settings):
        user = getattr(request.state, "user", None)
        if not user or not user.get("id"):
            raise HTTPException(401, "未登录")
        return user
    user_id = get_session_user_id(request)
    if not user_id:
        raise HTTPException(401, "未登录")
    user = Repository().get_user(user_id)
    if not user or not user.get("is_active"):
        raise HTTPException(401, "账号无效或已停用")
    return user


def require_admin(request: Request) -> dict:
    user = require_user(request)
    # platform 模式：团队共享主数据（产品/方向/账号/配置），任一主站登录用户均可管理
    if is_platform_mode():
        return user
    if user.get("role") != "admin":
        raise HTTPException(403, "需要管理员权限")
    return user
