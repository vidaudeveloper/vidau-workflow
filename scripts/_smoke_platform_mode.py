"""集成自检：platform 鉴权模式下，主站用户(含积分)贯通到 /api/user/me 与 /api/meta。

主站真实调用被 monkeypatch（不依赖在线 token），专注验证我们这侧的鉴权链路。
"""
import os
import sys
from pathlib import Path

os.environ["AUTH_ENABLED"] = "true"
os.environ["AUTH_MODE"] = "platform"
os.environ["PLATFORM_API_URL"] = "https://app-api.vidau.info/api"
os.environ["AUTH_DEV_FALLBACK"] = "false"
os.environ.pop("DATABASE_URL", None)  # 用 SQLite，专注鉴权
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import src.auth.platform_auth as pa  # noqa: E402
from src.platform.client import UserProfile  # noqa: E402

FAKE = UserProfile(user_id="u_test_888", coin=888.0, nickname="测试用户", avatar="http://x/a.png")


async def _fake_get_user_info(self, token):  # noqa: ANN001
    return FAKE


# patch 主站在线调用
from src.platform import client as client_mod  # noqa: E402
client_mod.PlatformClient.get_user_info = _fake_get_user_info
pa._USER_PROFILE_CACHE.clear() if hasattr(pa, "_USER_PROFILE_CACHE") else None

from fastapi.testclient import TestClient  # noqa: E402
from src.app import app  # noqa: E402

with TestClient(app) as client:
    # 无 token → 应被拒（401/403/重定向）
    anon = client.get("/api/user/me", follow_redirects=False)
    print("无 token /api/user/me ->", anon.status_code)
    assert anon.status_code in (401, 403, 302, 307), anon.status_code

    # 带 token（query 参数）→ 主站身份 + 积分
    me = client.get("/api/user/me?token=faketoken123", follow_redirects=False)
    print("带 token /api/user/me ->", me.status_code, me.text[:200])
    assert me.status_code == 200, me.text
    mj = me.json()
    assert mj["user_id"] == "u_test_888", mj
    assert mj["coin"] == 888, mj
    print("  user_id =", mj["user_id"], "| coin =", mj["coin"], "| nickname =", mj["nickname"])

    meta = client.get("/api/meta?token=faketoken123", follow_redirects=False)
    assert meta.status_code == 200, meta.text
    assert meta.json().get("auth_mode") == "platform", meta.json().get("auth_mode")
    print("/api/meta auth_mode =", meta.json().get("auth_mode"))

print("PLATFORM-MODE SMOKE OK")
