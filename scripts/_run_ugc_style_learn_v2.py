"""Learn UGC style from user's reference video library + product photos."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import httpx

BASE = "http://127.0.0.1:8787"
ROOT = Path(__file__).resolve().parents[1]

VIDEOS = [
    r"C:\Users\ninoo\Downloads\1.mp4",
    r"D:\video_analysis\Batch1\5bea600e-5d0e-49a9-a672-e7daf9125d53.mp4",
    r"D:\video_analysis\Batch1\video-task-1766387268600-0.4666203998097578.mp4",
    r"D:\video_analysis\Batch1\video-task-1766387434422-0.7419636494678954.mp4",
    r"D:\video_analysis\Batch1\video-task-1766387455536-0.9250422672593303.mp4",
    r"D:\video_analysis\Batch1\video-task-1766387435062-0.900513831497208.mp4",
    r"D:\video_analysis\Batch2\video-task-1766392535540-0.4998439221366401.mp4",
    r"D:\video_analysis\Batch2\video-task-1766392555985-0.027952304374407988.mp4",
]

FRAME_IMAGES = [
    Path(r"C:\Users\ninoo\.cursor\projects\c-Users-ninoo-bluetti-material-workflow\assets\c__Users_ninoo_AppData_Roaming_Cursor_User_workspaceStorage_empty-window_images_frame_07-147124a6-7307-4ba3-821b-99b74761830a.png"),
    Path(r"C:\Users\ninoo\.cursor\projects\c-Users-ninoo-bluetti-material-workflow\assets\c__Users_ninoo_AppData_Roaming_Cursor_User_workspaceStorage_empty-window_images_frame_15-89999546-e940-46fa-a467-92c0fde5eace.png"),
    Path(r"C:\Users\ninoo\.cursor\projects\c-Users-ninoo-bluetti-material-workflow\assets\c__Users_ninoo_AppData_Roaming_Cursor_User_workspaceStorage_empty-window_images_video-task-1766392555772-0.16061344723458082-226939fa-affb-48d9-b13c-0b0985807671.png"),
]


def main() -> int:
    files_vid = []
    for p in VIDEOS:
        path = Path(p)
        if not path.is_file():
            print("SKIP missing", p)
            continue
        files_vid.append(
            ("reference_videos", (path.name, path.read_bytes(), "video/mp4"))
        )
    print("videos", len(files_vid))

    files_img = []
    for p in FRAME_IMAGES:
        if p.is_file():
            files_img.append(("product_images", (p.name, p.read_bytes(), "image/png")))
    # product catalog images
    with httpx.Client(timeout=60) as c:
        prod = c.get(f"{BASE}/api/products/1a0b8a74").json()
        urls = json.loads(prod.get("image_urls_json") or "[]")
        for i, url in enumerate(urls[:3]):
            r = c.get(f"{BASE}{url}", timeout=60)
            if r.status_code == 200:
                files_img.append(
                    (f"product_images", (f"product_{i}.png", r.content, "image/png"))
                )

    with httpx.Client(timeout=600) as c:
        r = c.post(
            f"{BASE}/api/workflows/reference/learn-style",
            data={
                "user_note": "Learn TikTok UGC creator styling, lifestyle CTA ending, powder texture from product photos not wrong video render.",
                "product_hint": "PopSmilz Oral Probiotics strawberry mint popping powder",
            },
            files=files_vid + files_img,
        )
        print("learn", r.status_code)
        if r.status_code >= 400:
            print(r.text[:800])
            return 1
        out = r.json()
        (ROOT / "data" / "_ugc_style_learn.json").write_text(
            json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        decomp_id = out["decomposition_id"]
        payload = out["payload"]
        cp = payload.get("creator_persona", {})
        pv = payload.get("product_visual_truth", {})
        print("decomp_id", decomp_id)
        print("creator", json.dumps(cp, ensure_ascii=False, indent=2))
        print("product_visual", json.dumps(pv, ensure_ascii=False, indent=2))
        print("cta", payload.get("cta_pattern", "")[:200])

        # blueprint v2
        br = c.post(
            f"{BASE}/api/workflows/blueprints/from-decomposition",
            json={
                "decomposition_id": decomp_id,
                "product_id": "1a0b8a74",
                "reference_mode": "structure_clone",
            },
            timeout=60,
        )
        wf = br.json()["workflow_id"]
        c.patch(
            f"{BASE}/api/workflows/blueprints/{wf}",
            json={
                "creative": {
                    "scene_style": "airport terminal seats, suitcase, travel lifestyle, real daylight",
                    "acceptance_points": [
                        "Creator with distinctive wardrobe + manicured nails memory hook",
                        "POV open sachet showing pale pink-white popping powder per product photos",
                        "11-15s CTA: product on suitcase + urgency purchase line",
                        "15s single segment native audio + burned subtitles",
                    ],
                },
            },
            timeout=30,
        )
        c.post(f"{BASE}/api/workflows/blueprints/{wf}/confirm", timeout=30)
        conf = c.get(f"{BASE}/api/workflows/blueprints/{wf}/confirmation", timeout=30).json()
        (ROOT / "data" / "_ugc_v2_confirmation.json").write_text(
            json.dumps(conf, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        cr = c.post(
            f"{BASE}/api/batches",
            json={
                "product": "1a0b8a74",
                "direction": "Product B-Roll Remix",
                "count": 1,
                "language": "英语",
                "workflow_id": wf,
                "extra_instruction": "Match learned UGC creator persona; pale pink-white powder from product photos; strong lifestyle CTA ending.",
            },
            timeout=30,
        )
        batch_id = cr.json()["batch_id"]
        print("batch", batch_id, "workflow", wf)

        # poll script
        script_id = ""
        for _ in range(40):
            scripts = c.get(f"{BASE}/api/scripts", params={"batch_id": batch_id}).json()
            if scripts and scripts[0].get("review_status") == "待审核":
                script_id = scripts[0]["id"]
                break
            if scripts and scripts[0].get("review_status") == "失败":
                print("script fail", scripts[0].get("review_note", "")[:300])
                return 1
            time.sleep(8)
        c.post(
            f"{BASE}/api/scripts/{script_id}/review",
            json={"status": "通过", "note": "ugc v2", "reviewer": "runner"},
        )

        prompt_id = ""
        for _ in range(40):
            prompts = c.get(f"{BASE}/api/prompts", timeout=30).json()
            m = [p for p in prompts if p.get("script_id") == script_id]
            if m and m[0].get("review_status") == "待审核":
                prompt_id = m[0]["id"]
                break
            time.sleep(8)
        c.post(
            f"{BASE}/api/prompts/{prompt_id}/review",
            json={"status": "通过", "note": "ugc v2"},
        )
        vid = f"V{prompt_id}"
        print("video", vid, "generating...")

        for _ in range(90):
            vids = c.get(f"{BASE}/api/videos", timeout=60).json()
            v = next((x for x in vids if x.get("id") == vid), None)
            if v and v.get("output_status") in ("待交付", "已交付"):
                result = {
                    "workflow_id": wf,
                    "batch_id": batch_id,
                    "video_id": vid,
                    "video_url": v.get("video_url"),
                    "subtitle_status": v.get("subtitle_status"),
                    "note": v.get("note"),
                }
                (ROOT / "data" / "_ugc_v2_result.json").write_text(
                    json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                print("DONE", json.dumps(result, ensure_ascii=False))
                return 0
            if v and v.get("output_status") == "失败":
                print("FAIL", v.get("fail_reason", ""))
                return 1
            time.sleep(20)
    print("TIMEOUT")
    return 1


if __name__ == "__main__":
    sys.exit(main())
