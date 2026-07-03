"""数据访问范围 — 批次按登录用户隔离，主数据全员共享。"""

from __future__ import annotations

from fastapi import HTTPException, Request

from src.auth.deps import is_platform_mode, require_user
from src.config import get_settings
from src.db.repository import Repository


def access_context(request: Request) -> dict:
    """返回当前请求的访问上下文。"""
    user = require_user(request)
    settings = get_settings()
    auth_on = settings.auth_enabled
    # platform 模式：批次/脚本/成片按主站 userId 隔离（每用户只见自己的）
    if auth_on and is_platform_mode(settings):
        return {
            "user": user,
            "auth_enabled": True,
            "admin": False,
            "owner_user_id": user.get("id", ""),
        }
    admin = (not auth_on) or user.get("role") == "admin"
    return {
        "user": user,
        "auth_enabled": auth_on,
        "admin": admin,
        "owner_user_id": None if admin or not auth_on else user.get("id", ""),
    }


def batch_owned_by(batch: dict | None, ctx: dict) -> bool:
    if not batch:
        return False
    if not ctx.get("auth_enabled") or ctx.get("admin"):
        return True
    return (batch.get("owner_user_id") or "") == (ctx.get("owner_user_id") or "")


def ensure_batch_access(batch_id: str, request: Request, repo: Repository | None = None) -> dict:
    repo = repo or Repository()
    batch = repo.get_batch(batch_id)
    if not batch:
        raise HTTPException(404, "批次不存在")
    ctx = access_context(request)
    if not batch_owned_by(batch, ctx):
        raise HTTPException(403, "无权访问该批次")
    return batch


def ensure_script_access(script_id: str, request: Request, repo: Repository | None = None) -> dict:
    repo = repo or Repository()
    script = repo.get_script(script_id)
    if not script:
        raise HTTPException(404, "脚本不存在")
    ensure_batch_access(script["batch_id"], request, repo)
    return script


def ensure_prompt_access(prompt_id: str, request: Request, repo: Repository | None = None) -> dict:
    repo = repo or Repository()
    prompt = repo.get_prompt(prompt_id)
    if not prompt:
        raise HTTPException(404, "Prompt 不存在")
    ensure_script_access(prompt["script_id"], request, repo)
    return prompt


def ensure_video_access(video_id: str, request: Request, repo: Repository | None = None) -> dict:
    repo = repo or Repository()
    video = repo.get_video(video_id)
    if not video:
        raise HTTPException(404, "视频不存在")
    ensure_script_access(video["script_id"], request, repo)
    return video


def default_creator(ctx: dict, fallback: str = "") -> str:
    user = ctx.get("user") or {}
    return (
        fallback.strip()
        or user.get("display_name", "").strip()
        or user.get("email", "").strip()
        or "未命名"
    )
