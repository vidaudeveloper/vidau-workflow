"""主站联调自检 — 验证 PLATFORM_API_URL + VidAu-Token 是否可解析 userId / 积分。

用法（PowerShell）：
  # 1) 登录 vidau-editor 测试站，从浏览器 Cookie 复制 VidAu-Token 的值
  # 2) 运行（token 与 PLATFORM_API_URL 必须同环境：测试 .info / 生产 .ai）
  python scripts/check_platform.py --token "粘贴的JWT"
  # 或指定地址：
  python scripts/check_platform.py --token "JWT" --base https://app-api.vidau.info/api

成功标准：打印出 code∈{0,100,200} 且有 userId（可选 coin）。
"""

from __future__ import annotations

import argparse
import asyncio
import json

from src.config import get_settings
from src.platform.client import PlatformClient, PlatformError, _build_headers


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--token", required=True, help="主站 VidAu-Token (JWT)")
    parser.add_argument("--base", default="", help="覆盖 PLATFORM_API_URL")
    args = parser.parse_args()

    settings = get_settings()
    if args.base:
        settings = settings.model_copy(update={"platform_api_url": args.base})

    base = (settings.platform_api_url or "").rstrip("/")
    print(f"PLATFORM_API_URL = {base}")
    print(f"X-Service-Auth   = {'(已配置)' if settings.service_auth_secret else '(无)'}")
    print(f"请求头           = {list(_build_headers(args.token, settings).keys())}")
    print("-" * 50)

    client = PlatformClient(settings)
    try:
        profile = await client.get_user_info(args.token)
    except PlatformError as exc:
        print("[FAIL] 主站调用失败：", exc)
        print("   排查：token 是否过期 / 与 PLATFORM_API_URL 是否同环境 / 网络能否访问主站")
        return
    print("[OK] 主站连通，getUserInfo 成功：")
    print(json.dumps(
        {
            "user_id": profile.user_id,
            "coin": profile.coin,
            "nickname": profile.nickname,
            "avatar": profile.avatar,
        },
        ensure_ascii=False,
        indent=2,
    ))
    print("-" * 50)
    print("下一步：在 .env 设 AUTH_ENABLED=true、AUTH_MODE=platform，")
    print("访问 http://127.0.0.1:8787/?token=<同一JWT> 即可用主站身份登录。")


if __name__ == "__main__":
    asyncio.run(main())
