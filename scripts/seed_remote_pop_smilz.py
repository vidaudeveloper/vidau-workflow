#!/usr/bin/env python3
"""将本地 PopSmilz 产品 + 参考拆解同步到远程 AdFlow（测试服 auth 关闭时可用）。"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import httpx

DB = ROOT / "data" / "workflow.db"
PRODUCT_ID = "1a0b8a74"
DECOMP_ID = "style_20260630161257_94991a"


def _export_popsmilz_bundle() -> dict:
    from src.config_sync import _pick, _PRODUCT_EXPORT_KEYS, _read_local_image
    from src.db.repository import Repository
    from src.uploads import parse_product_image_urls

    repo = Repository()
    prod = repo.get_product(PRODUCT_ID)
    if not prod:
        raise SystemExit(f"本地无产品 {PRODUCT_ID}")
    item = _pick(prod, _PRODUCT_EXPORT_KEYS)
    item["product_specs_confirmed"] = bool(int(prod.get("product_specs_confirmed") or 0))
    images = []
    for url in parse_product_image_urls(prod):
        blob = _read_local_image(url)
        if blob:
            images.append(blob)
    if not images:
        raise SystemExit("PopSmilz 无本地产品图，无法导入远程")
    item["images"] = images
    return {
        "version": 1,
        "kind": "fixed_config",
        "exported_at": datetime.now(UTC).isoformat(),
        "products": [item],
        "accounts": [],
        "directions": [],
    }


def _load_decomposition() -> dict:
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT * FROM reference_decompositions WHERE id = ?", (DECOMP_ID,)
    ).fetchone()
    if not row:
        raise SystemExit(f"本地无拆解 {DECOMP_ID}")
    return dict(row)


def seed(base: str) -> None:
    base = base.rstrip("/")
    bundle = _export_popsmilz_bundle()
    decomp = _load_decomposition()

    with httpx.Client(timeout=120) as c:
        meta = c.get(f"{base}/api/meta")
        meta.raise_for_status()
        print("remote domain:", meta.json().get("app_domain"))

        ir = c.post(f"{base}/api/config/import", json={"bundle": bundle})
        if ir.status_code >= 400:
            raise SystemExit(f"import failed: {ir.status_code} {ir.text[:400]}")
        print("import stats:", ir.json().get("stats"))

        sr = c.post(
            f"{base}/api/workflows/reference/seed-decomposition",
            json={
                "id": decomp["id"],
                "source_url": decomp.get("source_url") or "",
                "source_filename": decomp.get("source_filename") or "",
                "payload": json.loads(decomp.get("payload_json") or "{}"),
            },
        )
        if sr.status_code == 404:
            print("WARN: seed-decomposition 404 — 请先部署含该 API 的最新 test 分支")
            return
        if sr.status_code >= 400:
            raise SystemExit(f"seed decomp failed: {sr.status_code} {sr.text[:400]}")
        print("seed decomp:", sr.json())

        chk = c.get(f"{base}/api/workflows/reference/{DECOMP_ID}")
        print("decomp check:", chk.status_code)
        prods = c.get(f"{base}/api/products").json()
        for p in prods:
            if "pop" in (p.get("name") or "").lower():
                print("remote product:", p.get("id"), p.get("name"))


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--base", default="https://adflow.vidau.info")
    args = p.parse_args()
    seed(args.base)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
