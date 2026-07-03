"""Burn subtitles onto batch6 raw videos and download _sub copies."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import httpx

BASE = "http://127.0.0.1:8787"
ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = Path(r"C:\Users\ninoo\Downloads\PopSmilz_NA_batch6_notext")
VIDEO_IDS = [
    "VPSB20260630170602-48080f-01",
    "VPSB20260630170602-48080f-02",
    "VPSB20260630170602-48080f-03",
    "VPSB20260630170602-48080f-04",
    "VPSB20260630170602-48080f-05",
]


def main() -> int:
    with httpx.Client(timeout=120) as c:
        for vid in VIDEO_IDS:
            r = c.post(f"{BASE}/api/videos/{vid}/burn-subtitles")
            print(vid, "queue", r.status_code, r.text[:120])

    deadline = time.time() + 1800
    results = []
    with httpx.Client(timeout=120) as c:
        pending = set(VIDEO_IDS)
        while pending and time.time() < deadline:
            vids = {v["id"]: v for v in c.get(f"{BASE}/api/videos").json()}
            for vid in list(pending):
                v = vids.get(vid, {})
                st = v.get("subtitle_status", "")
                print(vid, "subtitle_status=", st)
                if st == "已完成":
                    pending.discard(vid)
                elif "失败" in (v.get("note") or ""):
                    print("FAIL note:", v.get("note", "")[:200])
                    pending.discard(vid)
            time.sleep(15)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with httpx.Client(timeout=300) as c:
        for i, vid in enumerate(VIDEO_IDS, 1):
            v = next((x for x in c.get(f"{BASE}/api/videos").json() if x["id"] == vid), {})
            url = v.get("video_url", "")
            sub_url = url if "_sub" in url else f"/uploads/videos/{vid}_sub.mp4"
            dest = OUT_DIR / f"{i:02d}_{vid}_sub.mp4"
            r = c.get(f"{BASE}{sub_url}")
            if r.status_code != 200:
                r = c.get(f"{BASE}/uploads/videos/{vid}_sub.mp4")
            if r.status_code == 200:
                dest.write_bytes(r.content)
            results.append(
                {
                    "video_id": vid,
                    "subtitle_status": v.get("subtitle_status"),
                    "subtitle_align_status": v.get("subtitle_align_status"),
                    "video_url": sub_url if r.status_code == 200 else url,
                    "local": str(dest) if dest.is_file() else "",
                    "note": v.get("note", ""),
                }
            )

    summary = {"videos": results, "completed": sum(1 for x in results if x.get("subtitle_status") == "已完成")}
    (ROOT / "data" / "_na_batch6_burn_sub_result.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("DONE", json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["completed"] == 5 else 1


if __name__ == "__main__":
    sys.exit(main())
