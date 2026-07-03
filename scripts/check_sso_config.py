"""生产/测试 SSO 配置自检 — 在服务器上运行：

  cd /opt/vidau-workflow && python scripts/check_sso_config.py

成功标准：enabled=true，且 app_id / sdk_url 与当前环境一致。
"""

from __future__ import annotations

import json
import sys

from src.auth.sso import sso_disabled_reason, sso_public_config
from src.config import INTERNAL_ENV, ROOT, get_settings


def main() -> int:
    settings = get_settings()
    sso = sso_public_config(settings)
    host = (settings.app_domain or settings.public_base_url or "").strip()

    print("=== SSO 配置自检 ===")
    print(f"config/internal.env 存在: {INTERNAL_ENV.is_file()}")
    print(f".env 存在:             {(ROOT / '.env').is_file()}")
    print(f"AUTH_ENABLED:          {settings.auth_enabled}")
    print(f"AUTH_MODE:             {settings.auth_mode or 'local'}")
    print(f"SSO_APP_ID:            {settings.sso_app_id or '(空)'}")
    print(f"APP_DOMAIN:            {settings.app_domain or '(空)'}")
    print(f"PUBLIC_BASE_URL:       {settings.public_base_url or '(空)'}")
    print(f"PLATFORM_API_URL:      {settings.platform_api_url or '(空)'}")
    print("-" * 50)
    print("sso/config 等效输出:")
    print(json.dumps(sso, ensure_ascii=False, indent=2))

    errors: list[str] = []
    if not settings.auth_enabled:
        errors.append("AUTH_ENABLED=false，/login 会直接跳首页，不会出现登录页")
    reason = sso_disabled_reason(settings)
    if reason:
        errors.append(reason)
    if "vidau.ai" in host and (settings.sso_app_id or "") != "ad-flow-agent":
        errors.append(f"正式域名应使用 SSO_APP_ID=ad-flow-agent，当前: {settings.sso_app_id!r}")
    if "vidau.info" in host and (settings.sso_app_id or "") != "ad-flow-agent-test":
        errors.append(f"测试域名应使用 SSO_APP_ID=ad-flow-agent-test，当前: {settings.sso_app_id!r}")

    if errors:
        print("\n问题:")
        for e in errors:
            print(f"  - {e}")
        print("\n正式服 .env 至少需包含（参考 config/env.production.snippet）:")
        print("  AUTH_ENABLED=true")
        print("  AUTH_MODE=platform")
        print("  SSO_APP_ID=ad-flow-agent")
        print("  APP_DOMAIN=adflow.vidau.ai")
        print("  PUBLIC_BASE_URL=https://adflow.vidau.ai")
        print("  PLATFORM_API_URL=https://app-api.vidau.ai/api")
        print("\n修改后: sudo systemctl restart bluetti-workflow")
        return 1

    print("\n通过。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
