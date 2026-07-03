"""NA batch x5: no on-screen text + subtitles skip (raw for post)."""
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
OUT_DIR = Path(r"C:\Users\ninoo\Downloads\PopSmilz_NA_batch6_notext")

NA_CREATOR = {
    "archetype": "North American TikTok travel/lifestyle micro-creator (US/Canada, Gen-Z/Millennial)",
    "wardrobe": "light-wash denim jacket over white hoodie, blue jeans, airport athleisure",
    "hair_makeup": "natural curls or ponytail, minimal makeup, relatable NA look",
    "accessories": "cream headphones on neck; nude nails with black dot accents; simple bracelet",
    "energy": "high-energy direct-to-camera US TikTok creator; casual native English",
    "memory_hook": "airport travel-hack friend — POV nail-art hands or denim-jacket creator",
    "audience": "North American TikTok shoppers 18-35",
    "avoid": ["stiff AI face", "on-screen text", "over-polished TV ad"],
}

CTA_PATTERN = (
    "11-15s: airport blur + suitcase foreground + product centered + red down-arrow ICON only; "
    "NO readable text on screen; urgency in voiceover only"
)

PRODUCT_TRUTH = {
    "source": "product_photos",
    "powder_or_texture": "pale pink-white fine dry popping powder in POV open sachet",
    "packaging": "white/teal PopSmilz pouch + slim sachet, strawberry-mint graphics",
    "hero_shots": [
        "POV open sachet pale pink-white powder",
        "airport seat creator holds sachet",
        "11-15s suitcase CTA arrow icon only",
    ],
    "do_not_copy_from_video": ["wrong powder color", "on-screen marketing text"],
}


def main() -> int:
    wf = ""
    batch_id = ""
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
                "production": {"subtitles": "skip"},
                "creative": {
                    "scene_style": "real US airport terminal, suitcase, natural daylight",
                    "creator_persona": NA_CREATOR,
                    "product_visual_truth": PRODUCT_TRUTH,
                    "cta_pattern": CTA_PATTERN,
                    "acceptance_points": [
                        "NO readable text/subtitles in generated video — icons only",
                        "Red down-arrow sticker OK on CTA frame",
                        "Native English voiceover; subtitles skipped for post",
                        "Pale pink-white powder from product photos",
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
                "count": 5,
                "language": "英语",
                "workflow_id": wf,
                "extra_instruction": (
                    "North American TikTok UGC. NO on-screen text or captions in video — "
                    "arrow/sparkle icon stickers only. CTA ending: suitcase + product + red arrow icon. "
                    "Marketing copy voiceover only. Subtitles added manually in post."
                ),
            },
        )
        if cr.status_code >= 400:
            print("batch fail", cr.status_code, cr.text[:500])
            return 1
        batch_id = cr.json()["batch_id"]
        print("batch", batch_id, "autopilot x5 (no-text, subtitles skip)")

    done: list[dict] = []
    deadline = time.time() + 3600
    with httpx.Client(timeout=120) as c:
        while time.time() < deadline:
            vids = [
                v
                for v in c.get(f"{BASE}/api/videos").json()
                if v.get("batch_id") == batch_id
            ]
            finished = [
                v for v in vids if v.get("output_status") in ("待交付", "已交付")
            ]
            failed = [v for v in vids if v.get("output_status") == "失败"]
            print(f"videos={len(vids)}/5 done={len(finished)} fail={len(failed)}")
            if len(finished) >= 5 or (failed and len(finished) + len(failed) >= 5):
                done = finished
                break
            time.sleep(25)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    results = []
    with httpx.Client(timeout=300) as c:
        for i, v in enumerate(done, 1):
            url = v.get("video_url", "")
            if not url:
                continue
            # prefer raw (no _sub) when subtitles skipped
            vid = v["id"]
            raw_url = url.replace("_sub.mp4", ".mp4") if "_sub" in url else url
            for try_url in (raw_url, url):
                r = c.get(f"{BASE}{try_url}")
                if r.status_code == 200:
                    suffix = "raw" if try_url == raw_url else "sub"
                    dest = OUT_DIR / f"{i:02d}_{vid}_{suffix}.mp4"
                    dest.write_bytes(r.content)
                    results.append(
                        {
                            "index": i,
                            "video_id": vid,
                            "video_url": try_url,
                            "local": str(dest),
                            "subtitle_status": v.get("subtitle_status"),
                        }
                    )
                    break

    summary = {
        "workflow_id": wf,
        "batch_id": batch_id,
        "completed": len(done),
        "subtitles": "skip",
        "videos": results,
    }
    (ROOT / "data" / "_na_batch6_notext_result.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("DONE", json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if len(done) >= 5 else 1


if __name__ == "__main__":
    sys.exit(main())
