"""初始化登录用户（管理员等）。"""

from __future__ import annotations

import uuid

from src.auth.password import hash_password
from src.config import get_settings
from src.db.repository import Repository


def ensure_admin_user(repo: Repository | None = None) -> str | None:
    """若启用鉴权且尚无用户，按 .env 创建管理员。返回 user_id 或 None。"""
    settings = get_settings()
    if not settings.auth_enabled:
        return None
    repo = repo or Repository()
    if repo.count_users() > 0:
        return None
    email = (settings.admin_email or "").strip().lower()
    password = settings.admin_password or ""
    if not email or not password:
        raise RuntimeError(
            "AUTH_ENABLED=true 但尚未创建用户。请在 .env 设置 ADMIN_EMAIL / ADMIN_PASSWORD 后重启，"
            "或运行: python scripts/setup_workflow.py create-admin"
        )
    user_id = str(uuid.uuid4())
    repo.create_user(
        {
            "id": user_id,
            "email": email,
            "password_hash": hash_password(password),
            "display_name": settings.admin_display_name or "管理员",
            "role": "admin",
            "is_active": 1,
        }
    )
    return user_id
