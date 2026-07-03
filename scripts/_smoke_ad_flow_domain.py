"""本地冒烟：SSO / 域名配置（读取当前服务 settings，不硬编码生产域名）。"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8787"


def get(path: str) -> tuple[int, dict]:
    req = urllib.request.Request(f"{BASE}{path}")
    with urllib.request.urlopen(req, timeout=10) as resp:
        return resp.status, json.loads(resp.read().decode())


def main() -> int:
    errors: list[str] = []

    try:
        status, health = get("/health")
        if status != 200 or health.get("status") != "ok":
            errors.append(f"/health 异常: {status} {health}")
    except urllib.error.URLError as exc:
        print(f"无法连接 {BASE}，请先启动: python scripts/run_batch.py serve")
        print(exc)
        return 1

    _, meta = get("/api/meta")
    app_domain = meta.get("app_domain") or ""
    sso = meta.get("sso") or {}
    app_id = sso.get("app_id") or ""
    sdk_url = sso.get("sdk_url") or ""
    env_name = sso.get("env") or ""

    if not sso.get("enabled"):
        errors.append(f"sso.enabled 应为 true（AUTH_MODE=platform + SSO_APP_ID），实际: {sso}")
    elif not app_id:
        errors.append("sso.app_id 为空")

    is_test_host = "vidau.info" in app_domain or app_domain.endswith("adflow.vidau.info")
    if is_test_host:
        if app_id != "ad-flow-agent-test":
            errors.append(f"测试域名应使用 SSO_APP_ID=ad-flow-agent-test，实际: {app_id!r}")
        if env_name != "development":
            errors.append(f"测试域名 sso.env 应为 development，实际: {env_name!r}")
        if "sso.vidau.info" not in sdk_url:
            errors.append(f"测试 sso.sdk_url 应指向 sso.vidau.info: {sdk_url!r}")
    else:
        if app_id != "ad-flow-agent":
            errors.append(f"正式域名应使用 SSO_APP_ID=ad-flow-agent，实际: {app_id!r}")
        if env_name != "production":
            errors.append(f"正式域名 sso.env 应为 production，实际: {env_name!r}")
        if "sso.vidau.ai" not in sdk_url:
            errors.append(f"正式 sso.sdk_url 应指向 sso.vidau.ai: {sdk_url!r}")

    _, sso_cfg = get("/api/auth/sso/config")
    if sso_cfg.get("app_id") != app_id:
        errors.append(f"/api/auth/sso/config app_id={sso_cfg.get('app_id')!r}")

    login_html = urllib.request.urlopen(f"{BASE}/login", timeout=10).read().decode()
    for needle in ("sso-login", "VidauSsoHelper", "/assets/sso.js"):
        if needle not in login_html:
            errors.append(f"/login 页面缺少: {needle}")

    if meta.get("auth_mode") != "platform":
        errors.append(f"auth_mode={meta.get('auth_mode')!r}，期望 platform")

    print("=== Flow SSO 本地冒烟 ===")
    print(f"health: ok")
    print(f"public_base_url: {meta.get('public_base_url')}")
    print(f"app_domain:      {app_domain}")
    print(f"auth_mode:       {meta.get('auth_mode')}")
    print(f"sso:             {json.dumps(sso, ensure_ascii=False)}")
    print(f"login:           SSO 面板 + sso.js 已挂载")

    if errors:
        print("\n失败项:")
        for e in errors:
            print(f"  - {e}")
        return 1

    print("\n全部通过。浏览器打开 http://127.0.0.1:8787/login 可测 SSO 弹窗。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
