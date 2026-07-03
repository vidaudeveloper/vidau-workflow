"""PopSmilz v3: 1.mp4 product ref video + 15 Gemini directions + post subtitles."""
from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

import httpx

BASE = "http://127.0.0.1:8787"
ROOT = Path(__file__).resolve().parents[1]
PRODUCT_ID = "1a0b8a74"
REF_MP4 = Path(r"C:\Users\ninoo\Downloads\1.mp4")
OUT_DIR = Path(r"C:\Users\ninoo\Downloads\PopSmilz_GeminiV3_batch5")
DECOMP_ID = "style_20260630161257_94991a"
COUNT = 5
DIRECTION_START = 1  # use directions 1-5


async def _product_decompose() -> dict:
    from src.config import get_settings
    from src.pipeline.reference_product_decompose import decompose_product_reference_video
    from src.pipeline.reference_product_frames import extract_product_frames
    from src.uploads import save_local_reference_video

    settings = get_settings()
    if not REF_MP4.is_file():
        raise FileNotFoundError(REF_MP4)
    ref_url = save_local_reference_video(REF_MP4)
    # 1.mp4 帧常含真人，Seedance reference_image 会拒收；仅用产品图 + 拆解文案
    frame_urls: list[str] = []
    data = REF_MP4.read_bytes()
    result = await decompose_product_reference_video(
        settings,
        video_bytes=data,
        filename=REF_MP4.name,
        product_hint="PopSmilz Oral Probiotics",
        user_note="Only product tear/powder/packaging; ignore people and plot.",
    )
    result["ref_url"] = ref_url
    result["frame_urls"] = frame_urls
    (ROOT / "data" / "_1mp4_product_decompose.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return result


def main() -> int:
    prod_decomp = asyncio.run(_product_decompose())
    ref_url = prod_decomp["ref_url"]
    frame_urls = prod_decomp.get("frame_urls") or []
    pv = prod_decomp.get("payload") or {}
    product_truth = {
        "source": "reference_video_1mp4",
        "sachet_tear_method": pv.get("sachet_tear_method", "horizontal tear across top seal"),
        "powder_or_texture": pv.get(
            "powder_appearance", "pale pink-white micro-encapsulated popping powder"
        ),
        "packaging": pv.get("packaging_appearance", "white-teal PopSmilz sachet and pouch"),
        "hero_shots": pv.get("hero_product_actions") or [
            "horizontal tear sachet",
            "reveal powder",
            "pour to mouth",
        ],
        "do_not_copy_from_video": pv.get("do_not_copy_from_video") or [
            "people",
            "plot",
            "background",
        ],
    }

    with httpx.Client(timeout=120) as c:
        br = c.post(
            f"{BASE}/api/workflows/blueprints/from-decomposition",
            json={
                "decomposition_id": DECOMP_ID,
                "product_id": PRODUCT_ID,
                "reference_mode": "structure_clone",
            },
        )
        if br.status_code >= 400:
            print("blueprint fail", br.text[:400])
            return 1
        wf = br.json()["workflow_id"]
        c.patch(
            f"{BASE}/api/workflows/blueprints/{wf}",
            json={
                "reference": {
                    "product_reference_video_url": ref_url,
                    "product_reference_frame_urls": frame_urls,
                    "product_reference_scope": "product_only",
                    "source": str(REF_MP4),
                },
                "production": {"subtitles": "skip"},
                "creative": {
                    "product_visual_truth": product_truth,
                    "narrative_rule": (
                        "15s UGC: 0-3s hook → 3-11s horizontal tear + powder demo → "
                        "11-15s CTA arrow icon + voiceover. Plot from direction library, "
                        "NOT from 1.mp4 people."
                    ),
                    "acceptance_points": [
                        "Horizontal tear across sachet top (from 1.mp4 product ref)",
                        "Pale pink-white popping powder macro",
                        "Fashionable NA TikTok creator per direction #1-5",
                        "No on-screen text; post subtitles",
                        "CTA: suitcase or scene + red arrow icon",
                    ],
                },
            },
        )
        c.post(f"{BASE}/api/workflows/blueprints/{wf}/confirm")
        cr = c.post(
            f"{BASE}/api/batches/autopilot",
            json={
                "product": PRODUCT_ID,
                "direction": "Product B-Roll Remix",
                "count": COUNT,
                "language": "英语",
                "workflow_id": wf,
                "extra_instruction": (
                    "Gemini-style UGC 15s beats. Each variant uses pop_smilz direction library "
                    f"#{DIRECTION_START}-{DIRECTION_START + COUNT - 1}. "
                    "POV/iPhone handheld, fashionable TikTok wardrobe, strong hook face/reaction. "
                    "MUST horizontal tear sachet. reference_video = product only from 1.mp4."
                ),
            },
        )
        if cr.status_code >= 400:
            print("batch fail", cr.text[:400])
            return 1
        batch_id = cr.json()["batch_id"]
        print("workflow", wf, "batch", batch_id)

    done: list[dict] = []
    deadline = time.time() + 3600
    with httpx.Client(timeout=120) as c:
        while time.time() < deadline:
            vids = [
                v
                for v in c.get(f"{BASE}/api/videos").json()
                if v.get("batch_id") == batch_id
            ]
            finished = [v for v in vids if v.get("output_status") in ("待交付", "已交付")]
            failed = [v for v in vids if v.get("output_status") == "失败"]
            print(f"done={len(finished)}/{COUNT} fail={len(failed)}")
            if len(finished) >= COUNT or (failed and len(finished) + len(failed) >= COUNT):
                done = finished
                break
            time.sleep(25)

    video_ids = [v["id"] for v in done]
    with httpx.Client(timeout=120) as c:
        for vid in video_ids:
            c.post(f"{BASE}/api/videos/{vid}/burn-subtitles")
        pending = set(video_ids)
        while pending and time.time() < deadline:
            for vid in list(pending):
                v = next((x for x in c.get(f"{BASE}/api/videos").json() if x["id"] == vid), {})
                if v.get("subtitle_status") == "已完成":
                    pending.discard(vid)
            time.sleep(12)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    results = []
    with httpx.Client(timeout=300) as c:
        for i, v in enumerate(done, 1):
            url = v.get("video_url", "")
            sub = url if "_sub" in url else url.replace(".mp4", "_sub.mp4")
            r = c.get(f"{BASE}{sub}")
            if r.status_code != 200:
                r = c.get(f"{BASE}{url}")
                sub = url
            dest = OUT_DIR / f"{i:02d}_{v['id']}_sub.mp4"
            if r.status_code == 200:
                dest.write_bytes(r.content)
            results.append({"video_id": v["id"], "local": str(dest), "url": sub})

    summary = {"workflow_id": wf, "batch_id": batch_id, "videos": results}
    (ROOT / "data" / "_gemini_v3_batch5_result.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("DONE", json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if len(results) >= COUNT else 1


if __name__ == "__main__":
    sys.exit(main())
