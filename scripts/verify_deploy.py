#!/usr/bin/env python3
"""部署后自检：域名、Workflow API、计费模式。

用法:
  python scripts/verify_deploy.py --url https://adflow.vidau.info
  python scripts/verify_deploy.py --url http://127.0.0.1:8787 --expect-domain adflow.vidau.info
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request


def _get(url: str) -> tuple[int, dict]:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        try:
            return e.code, json.loads(body)
        except json.JSONDecodeError:
            return e.code, {"raw": body[:200]}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--url", required=True, help="站点根 URL，如 https://adflow.vidau.info")
    p.add_argument("--expect-domain", default="", help="期望 app_domain，如 adflow.vidau.info")
    args = p.parse_args()
    base = args.url.rstrip("/")
    errors: list[str] = []

    code, meta = _get(f"{base}/api/meta")
    if code != 200:
        errors.append(f"/api/meta HTTP {code}")
    else:
        domain = str(meta.get("app_domain") or "")
        pub = str(meta.get("public_base_url") or "")
        if "workflow.vidau" in domain or "workflow.vidau" in pub:
            errors.append(f"仍为旧域名 workflow.*：app_domain={domain!r} public_base_url={pub!r}")
        if args.expect_domain and domain != args.expect_domain:
            errors.append(f"app_domain 期望 {args.expect_domain!r}，实际 {domain!r}")
        billing = meta.get("billing") or {}
        if base.endswith(".vidau.info") and billing.get("billing_mode") not in (None, "none"):
            errors.append(f"测试服 billing_mode 应为 none，实际 {billing.get('billing_mode')!r}")
        if base.endswith(".vidau.info"):
            if meta.get("gemini_mode") != "vertex":
                errors.append(
                    f"测试服应使用 Vertex Gemini，实际 gemini_mode={meta.get('gemini_mode')!r}"
                )
            if not meta.get("gemini_configured"):
                errors.append(
                    "gemini_configured=false（git pull 后确认 config/gemini-vertex-sa.json 存在）"
                )

    # Workflow 路由应存在（未登录 401，不是 404）
    for path, method in (
        ("/api/workflows/blueprints", "GET"),
        ("/api/workflows/reference/learn-style", "POST"),
    ):
        req = urllib.request.Request(
            f"{base}{path}",
            data=b"{}" if method == "POST" else None,
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            method=method,
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                c = resp.status
        except urllib.error.HTTPError as e:
            c = e.code
        if c == 404:
            errors.append(f"{method} {path} 返回 404（代码未部署？）")
        elif c not in (200, 400, 401, 405, 422):
            errors.append(f"{method} {path} 意外状态 {c}")

    code, skills = _get(f"{base}/.well-known/skills/index.json")
    if code != 200:
        errors.append(f"GET /.well-known/skills/index.json HTTP {code}（Hermes Skill 远程安装不可用）")
    elif not (skills.get("skills") or []):
        errors.append("skills index 为空")
    else:
        names = [s.get("name") for s in skills["skills"]]
        for required in ("adflow-blueprint", "adflow-copy", "adflow-canvas"):
            if required not in names:
                errors.append(f"skills index 缺少 {required!r}")

    mcp_code = 0
    try:
        req = urllib.request.Request(
            f"{base}/mcp",
            method="GET",
            headers={"Accept": "application/json, text/event-stream"},
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            mcp_code = resp.status
    except urllib.error.HTTPError as e:
        mcp_code = e.code
    except urllib.error.URLError as e:
        errors.append(f"GET /mcp 不可达: {e}")
    if mcp_code == 404:
        errors.append("GET /mcp 返回 404（远程 MCP 未部署）")
    elif mcp_code == 0:
        pass
    elif mcp_code not in (200, 400, 405, 406, 307, 308):
        errors.append(f"GET /mcp 意外状态 {mcp_code}")

    if errors:
        print("部署自检失败:")
        for e in errors:
            print(f"  - {e}")
        return 1

    print("部署自检通过。")
    print(f"  app_domain={meta.get('app_domain')}")
    print(f"  billing_mode={(meta.get('billing') or {}).get('billing_mode')}")
    print(f"  gemini_mode={meta.get('gemini_mode')} configured={meta.get('gemini_configured')}")
    print(f"  hermes_skills={len(skills.get('skills') or [])} ({skills.get('package')})")
    print(f"  remote_mcp=/mcp (HTTP {mcp_code})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
