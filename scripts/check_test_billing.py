#!/usr/bin/env python3
"""测试服免扣费自检 — 核对 .env 与运行中 /api/meta 是否一致。

用法（测试机上）：
  python scripts/check_test_billing.py
  python scripts/check_test_billing.py --url https://adflow.vidau.info
  python scripts/check_test_billing.py --env-file /opt/vidau-workflow/.env --strict

成功标准：AIGC_BILLING_MODE=none 且 billing.charge_enabled=false。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def read_env_mode(env_file: Path) -> str | None:
    if not env_file.is_file():
        return None
    for line in env_file.read_text(encoding="utf-8", errors="replace").splitlines():
        m = re.match(r"^AIGC_BILLING_MODE=(.*)$", line.strip())
        if m:
            return m.group(1).strip().strip('"').strip("'").lower()
    return None


def fetch_billing_meta(url: str) -> dict:
    base = url.rstrip("/")
    req = urllib.request.Request(f"{base}/api/meta", headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    billing = payload.get("billing") or {}
    if not isinstance(billing, dict):
        raise RuntimeError("/api/meta 未返回 billing 对象")
    return billing


def main() -> int:
    parser = argparse.ArgumentParser(description="测试服免扣费配置自检")
    parser.add_argument(
        "--env-file",
        default=str(ROOT / ".env"),
        help="要检查的 .env 路径（默认仓库根目录 .env）",
    )
    parser.add_argument(
        "--url",
        default="http://127.0.0.1:8787",
        help="AdFlow 站点根 URL，用于拉取 /api/meta",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="任一检查失败时 exit 1（供 CI / 部署脚本使用）",
    )
    args = parser.parse_args()

    env_file = Path(args.env_file)
    ok = True
    issues: list[str] = []

    mode = read_env_mode(env_file)
    print(f".env 文件     : {env_file}")
    print(f"AIGC_BILLING_MODE (.env) : {mode or '(未设置)'}")

    if mode != "none":
        ok = False
        issues.append(
            "请在 .env 设置 AIGC_BILLING_MODE=none，或执行: bash scripts/apply_test_billing_none.sh"
        )

    try:
        billing = fetch_billing_meta(args.url)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, RuntimeError) as exc:
        ok = False
        issues.append(f"无法读取 {args.url.rstrip('/')}/api/meta: {exc}")
        billing = {}

    if billing:
        charge_enabled = bool(billing.get("charge_enabled"))
        billing_mode = str(billing.get("billing_mode") or "").lower()
        print(f"站点 URL      : {args.url.rstrip('/')}")
        print(f"billing_mode (live): {billing_mode or '(空)'}")
        print(f"charge_enabled (live): {charge_enabled}")
        if charge_enabled or billing_mode == "platform":
            ok = False
            issues.append(
                "运行中服务仍在扣费模式；修改 .env 后需 sudo systemctl restart bluetti-workflow"
            )

    print("-" * 50)
    if ok:
        print("[OK] 测试服已关闭出片扣费，SSO 账号可反复跑工作流。")
        return 0

    print("[FAIL] 测试服免扣费未生效：")
    for item in issues:
        print(f"  - {item}")
    return 1 if args.strict else 0


if __name__ == "__main__":
    sys.exit(main())
