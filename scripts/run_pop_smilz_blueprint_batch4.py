#!/usr/bin/env python3
"""PopSmilz 4×15s：Blueprint 驱动原生 viral UGC（方向库 1–4）。"""
from __future__ import annotations

import argparse
import json
import sys
import time

import httpx

PRODUCT_ID = "1a0b8a74"
DECOMPOSITION_ID = "style_20260630161257_94991a"
COUNT = 4


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--base", default="http://127.0.0.1:8787", help="AdFlow API base URL")
    p.add_argument("--autopilot", action="store_true", help="Full autopilot (else scripts only)")
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
            "acceptance_points": [
                "15s Seedance native audio — no post TTS/subtitle burn",
                "Directions 1–4 from pop_smilz_15_directions.json",
                "No TikTok logo on screen",
            ],
        },
        "batch": {
            "direction_library": "config/creative/pop_smilz_15_directions.json",
            "count_per_direction": COUNT,
        },
    }

    with httpx.Client(timeout=120) as c:
        meta = c.get(f"{base}/api/meta")
        if meta.status_code != 200:
            print("API unreachable:", meta.status_code, meta.text[:200])
            return 1
        print("app_domain:", meta.json().get("app_domain"))

        br = c.post(
            f"{base}/api/workflows/blueprints/from-decomposition",
            json={
                "decomposition_id": DECOMPOSITION_ID,
                "product_id": PRODUCT_ID,
                "reference_mode": "structure_clone",
                "platform": "tiktok",
                "goal": "conversion",
            },
        )
        if br.status_code >= 400:
            print("blueprint create failed:", br.status_code, br.text[:500])
            return 1
        wf = br.json().get("workflow_id")
        if not wf:
            print("no workflow_id in", br.json())
            return 1

        pr = c.patch(f"{base}/api/workflows/blueprints/{wf}", json=patch)
        if pr.status_code >= 400:
            print("patch failed:", pr.status_code, pr.text[:500])
            return 1

        conf = c.get(f"{base}/api/workflows/blueprints/{wf}/confirmation")
        if conf.status_code == 200:
            print("confirmation production:", json.dumps(
                conf.json().get("sections", {}).get("出片策略", {}),
                ensure_ascii=False,
            ))

        cf = c.post(f"{base}/api/workflows/blueprints/{wf}/confirm")
        if cf.status_code >= 400:
            print("confirm failed:", cf.status_code, cf.text[:300])
            return 1

        batch_body = {
            "product": PRODUCT_ID,
            "direction": "Product B-Roll Remix",
            "count": COUNT,
            "language": "英语",
            "workflow_id": wf,
            "extra_instruction": "秋反馈方向1-4；viral UGC native 15s；去AI味口播。",
        }
        path = "/api/batches/autopilot" if args.autopilot else "/api/batches"
        cr = c.post(f"{base}{path}", json=batch_body)
        if cr.status_code >= 400:
            print("batch failed:", cr.status_code, cr.text[:500])
            return 1
        batch_id = cr.json().get("batch_id")
        print("workflow_id:", wf)
        print("batch_id:", batch_id)
        print("mode:", "autopilot" if args.autopilot else "scripts-only")

        if not args.autopilot:
            deadline = time.time() + 600
            while time.time() < deadline:
                scripts = c.get(f"{base}/api/scripts", params={"batch_id": batch_id}).json()
                pending = [s for s in scripts if s.get("review_status") in ("排队中", "生成中")]
                ready = [s for s in scripts if s.get("review_status") == "待审核"]
                print(f"scripts ready={len(ready)}/{COUNT} pending={len(pending)}")
                if len(ready) >= COUNT:
                    break
                time.sleep(8)
    return 0


if __name__ == "__main__":
    sys.exit(main())
