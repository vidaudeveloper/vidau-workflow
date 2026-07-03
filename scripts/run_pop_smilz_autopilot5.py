#!/usr/bin/env python3
"""PopSmilz 5×15s autopilot：Blueprint + 方向库 1–5 + 全自动出片。"""
from __future__ import annotations

import argparse
import json
import sys
import time

import httpx

PRODUCT_NAME = "PopSmilz Oral Probiotics"
DECOMPOSITION_ID = "style_20260630161257_94991a"
COUNT = 5


def _resolve_product_id(client: httpx.Client, base: str) -> str:
    for p in client.get(f"{base}/api/products").json():
        if (p.get("name") or "").strip().lower() == PRODUCT_NAME.lower():
            return str(p["id"])
    raise SystemExit(f"远程无产品 {PRODUCT_NAME}")


def _videos_for_batch(client: httpx.Client, base: str, batch_id: str) -> list[dict]:
    scripts = client.get(f"{base}/api/scripts", params={"batch_id": batch_id}).json()
    script_ids = {s["id"] for s in scripts}
    return [v for v in client.get(f"{base}/api/videos").json() if v.get("script_id") in script_ids]


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--base", default="https://adflow.vidau.info")
    p.add_argument("--wait-min", type=int, default=120, help="最长等待出片分钟数")
    args = p.parse_args()
    base = args.base.rstrip("/")

    patch = {
        "video_spec": {
            "duration_sec": 15,
            "segment_strategy": "single",
            "segment_duration_sec": 15,
            "aspect_ratio": "9:16",
            "max_shots": 3,
        },
        "production": {
            "tts": False,
            "subtitles": "skip",
            "seedance_native_audio": True,
            "ugc_viral_format": True,
            "prompt_format": "viral_15s_blocks",
            "language": "英语",
        },
        "creative": {
            "prompt_profile": "ugc_15s",
            "storyboard_profile": "ugc_viral_15s",
            "reference_style": (
                "High-energy Gen-Z UGC TikTok; handheld POV; fashionable wardrobe; "
                "natural social hooks (couple/cafe/car/mask scenarios)."
            ),
            "narrative_rule": (
                "Natural seeding: breath awkward moment → (optional) friend points out → "
                "use product → fresh confidence → CTA thumb down, no on-screen text."
            ),
            "beat_structure": (
                "[0-3s Hook] scene + reaction [Voiceover: ...]; "
                "[3-10s Core] horizontal tear + powder per product_visual_truth [Voiceover: ...]; "
                "[10-15s CTA] smile + thumb down [Voiceover: ...]"
            ),
            "product_visual_truth": {
                "hero_product": "NC PopSmilz Oral Probiotics sachet",
                "appearance_notes": "pale pink-white micro-encapsulated granules",
                "tear_method": "horizontal tear across top seal",
            },
            "forbidden": [
                "TikTok logo",
                "platform watermark",
                "readable burned subtitles",
                "popcorn metaphor",
            ],
        },
        "batch": {
            "direction_library": "config/creative/pop_smilz_15_directions.json",
            "count_per_direction": 1,
        },
    }

    with httpx.Client(timeout=180) as c:
        product_id = _resolve_product_id(c, base)
        br = c.post(
            f"{base}/api/workflows/blueprints/from-decomposition",
            json={
                "decomposition_id": DECOMPOSITION_ID,
                "product_id": product_id,
                "reference_mode": "structure_clone",
                "platform": "tiktok",
                "goal": "conversion",
            },
        )
        br.raise_for_status()
        wf = br.json()["workflow_id"]
        c.patch(f"{base}/api/workflows/blueprints/{wf}", json=patch).raise_for_status()
        c.post(f"{base}/api/workflows/blueprints/{wf}/confirm").raise_for_status()

        cr = c.post(
            f"{base}/api/batches/autopilot",
            json={
                "product": product_id,
                "direction": "Product B-Roll Remix",
                "count": COUNT,
                "language": "英语",
                "workflow_id": wf,
                "extra_instruction": "秋反馈方向1-5；viral UGC native 15s；去AI味口播。",
            },
        )
        if cr.status_code >= 400:
            print("autopilot failed:", cr.status_code, cr.text[:500])
            return 1
        batch_id = cr.json()["batch_id"]
        pub = c.get(f"{base}/api/meta").json().get("public_base_url", base).rstrip("/")
        print("workflow_id:", wf)
        print("batch_id:", batch_id)
        print("canvas:", f"{pub}/hermes/canvas?batch_id={batch_id}")

        deadline = time.time() + args.wait_min * 60
        while time.time() < deadline:
            batches = {b["id"]: b for b in c.get(f"{base}/api/batches").json()}
            batch = batches.get(batch_id, {})
            status = batch.get("status", "")
            videos = _videos_for_batch(c, base, batch_id)
            done = [
                v
                for v in videos
                if (v.get("video_url") or "").strip()
                and v.get("output_status") not in ("生成中", "排队中", "")
            ]
            pending = [v for v in videos if v.get("output_status") in ("生成中", "排队中")]
            failed = [v for v in videos if v.get("output_status") == "失败"]
            print(
                f"batch={status!r} videos done={len(done)}/{COUNT} "
                f"pending={len(pending)} failed={len(failed)}"
            )
            if len(done) >= COUNT:
                break
            if status in ("生成失败", "失败") and not pending:
                break
            time.sleep(30)

        videos = _videos_for_batch(c, base, batch_id)
        print("\n=== 成片 ===")
        for i, v in enumerate(videos, 1):
            url = (v.get("video_url") or "").strip()
            if url and not url.startswith("http"):
                url = f"{pub}{url}"
            print(f"{i}. {v.get('output_status')} {v.get('theme', '')[:40]}")
            if url:
                print(f"   {url}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
