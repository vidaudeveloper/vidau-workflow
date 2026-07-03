"""NA TikTok persona + suitcase CTA blueprint → autopilot batch x5."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import httpx

BASE = "http://127.0.0.1:8787"
ROOT = Path(__file__).resolve().parents[1]
DECOMP_ID = "style_20260630161257_94991a"
PRODUCT_ID = "1a0b8a74"

NA_CREATOR = {
    "archetype": "North American TikTok travel/lifestyle micro-creator (US/Canada, Gen-Z/Millennial)",
    "wardrobe": (
        "light-wash denim jacket over white hoodie, blue jeans, airport athleisure; "
        "casual-cool American TikTok creator NOT runway model"
    ),
    "hair_makeup": (
        "natural hair (loose curls or ponytail), minimal clean makeup, "
        "relatable girl-next-door / guy-next-door North American look"
    ),
    "accessories": (
        "cream over-ear headphones on neck; nude manicure with small black dot accents; "
        "simple bracelet; travel backpack strap visible in airport shots"
    ),
    "energy": (
        "high-energy direct-to-camera like real US TikTok creator; casual native English; "
        "expressive face and hand gestures; authentic NOT corporate ad read"
    ),
    "memory_hook": (
        "your airport travel-hack friend — POV hands with nail art opening sachet, "
        "or denim-jacket creator talking in terminal seats"
    ),
    "audience": "North American TikTok shoppers 18-35, English casual native tone",
    "avoid": [
        "stiff AI face",
        "European luxury fashion",
        "K-beauty idol aesthetic",
        "over-polished TV commercial",
        "generic global model with no regional vibe",
    ],
}

CTA_PATTERN = (
    "11-15s MANDATORY closing: blurred airport terminal; grey hardshell suitcase handle in foreground; "
    "product pouch centered above suitcase; large red downward arrow sticker with white outline "
    "bottom-left (ICON ONLY — NO readable text on screen); "
    "urgency purchase lines in VOICEOVER only (e.g. Travelers grab yours fast / solve breath on every trip); "
    "post-production will add subtitles — do NOT render marketing copy in the video frame"
)

PRODUCT_TRUTH = {
    "source": "product_photos",
    "powder_or_texture": "pale pink-white fine dry popping powder, visible in POV open sachet",
    "packaging": "white/teal PopSmilz stand-up pouch + slim stick sachet, strawberry-mint graphics",
    "hero_shots": [
        "POV open sachet showing pale pink-white powder",
        "creator holds sachet to camera in airport seat",
        "powder pour-to-mouth demo mid-video",
        "11-15s product on suitcase CTA frame",
    ],
    "do_not_copy_from_video": ["wrong powder color from AI video renders"],
}


def main() -> int:
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
            print("blueprint fail", br.status_code, br.text[:500])
            return 1
        wf = br.json()["workflow_id"]
        print("workflow", wf)

        c.patch(
            f"{BASE}/api/workflows/blueprints/{wf}",
            json={
                "creative": {
                    "scene_style": (
                        "real US airport terminal — black seats, grey armrests, suitcase, "
                        "natural daylight, lived-in travel vibe"
                    ),
                    "creator_persona": NA_CREATOR,
                    "product_visual_truth": PRODUCT_TRUTH,
                    "cta_pattern": CTA_PATTERN,
                    "lifestyle_notes": (
                        "North American travel day-in-life: waiting at gate, rolling suitcase, "
                        "quick breath hack between flights — NOT studio"
                    ),
                    "acceptance_points": [
                        "Creator reads as North American TikTok native (denim jacket / POV nails)",
                        "Pale pink-white powder from product photos in POV sachet shot",
                        "11-15s suitcase + red down-arrow icon only (no on-screen CTA text)",
                        "15s single segment, native English audio; post subtitles only",
                    ],
                },
            },
        )
        c.post(f"{BASE}/api/workflows/blueprints/{wf}/confirm")
        conf = c.get(f"{BASE}/api/workflows/blueprints/{wf}/confirmation").json()
        (ROOT / "data" / "_na_batch5_confirmation.json").write_text(
            json.dumps(conf, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        cr = c.post(
            f"{BASE}/api/batches/autopilot",
            json={
                "product": PRODUCT_ID,
                "direction": "Product B-Roll Remix",
                "count": 5,
                "language": "英语",
                "workflow_id": wf,
                "extra_instruction": (
                    "North American TikTok UGC audience; denim-jacket creator or POV nail-art hands; "
                    "ending MUST be suitcase CTA with red arrow and grab-yours-fast copy."
                ),
            },
        )
        if cr.status_code >= 400:
            print("batch fail", cr.status_code, cr.text[:500])
            return 1
        batch_id = cr.json()["batch_id"]
        print("batch", batch_id, "autopilot x5 started")

    done: list[dict] = []
    deadline = time.time() + 3600
    with httpx.Client(timeout=120) as c:
        while time.time() < deadline:
            batch = next(
                (b for b in c.get(f"{BASE}/api/batches").json() if b.get("id") == batch_id),
                None,
            )
            status = (batch or {}).get("status", "")
            vids = [
                v
                for v in c.get(f"{BASE}/api/videos").json()
                if v.get("batch_id") == batch_id
            ]
            finished = [
                v
                for v in vids
                if v.get("output_status") in ("待交付", "已交付")
            ]
            failed = [v for v in vids if v.get("output_status") == "失败"]
            print(
                f"status={status} videos={len(vids)}/5 done={len(finished)} fail={len(failed)}"
            )
            if len(finished) >= 5:
                done = finished
                break
            if failed and len(finished) + len(failed) >= 5:
                done = finished
                break
            if status in ("已完成", "部分失败", "生成失败") and vids:
                done = finished
                if len(done) + len(failed) >= len(vids):
                    break
            time.sleep(25)

    out_dir = Path(r"C:\Users\ninoo\Downloads\PopSmilz_NA_batch5")
    out_dir.mkdir(parents=True, exist_ok=True)
    results = []
    with httpx.Client(timeout=300) as c:
        for i, v in enumerate(done, 1):
            url = v.get("video_url", "")
            if not url:
                continue
            name = f"{i:02d}_{v['id']}_sub.mp4" if "_sub" in url else f"{i:02d}_{v['id']}.mp4"
            dest = out_dir / name
            r = c.get(f"{BASE}{url}")
            if r.status_code == 200:
                dest.write_bytes(r.content)
            results.append(
                {
                    "index": i,
                    "video_id": v["id"],
                    "video_url": url,
                    "local": str(dest),
                    "subtitle_status": v.get("subtitle_status"),
                }
            )

    summary = {
        "workflow_id": wf,
        "batch_id": batch_id,
        "completed": len(done),
        "videos": results,
    }
    (ROOT / "data" / "_na_batch5_result.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("DONE", json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if len(done) >= 5 else 1


if __name__ == "__main__":
    sys.exit(main())
