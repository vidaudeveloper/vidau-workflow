"""Continue test plan P4–P6 from data/_test_plan_result.json (or env overrides)."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import httpx

BASE = "http://127.0.0.1:8787"
ROOT = Path(__file__).resolve().parents[1]
LOG: list[tuple[str, bool, str]] = []


def log(name: str, ok: bool, detail: str = "") -> None:
    LOG.append((name, ok, detail))
    tag = "PASS" if ok else "FAIL"
    line = f"[{tag}] {name}"
    if detail:
        line += f" — {detail}"
    print(line, flush=True)


def load_ctx() -> dict:
    path = ROOT / "data" / "_test_plan_result.json"
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def poll_video(client: httpx.Client, video_id: str, timeout_sec: int = 1800) -> dict:
    deadline = time.time() + timeout_sec
    last_status = ""
    while time.time() < deadline:
        videos = client.get(f"{BASE}/api/videos", timeout=60).json()
        v = next((x for x in videos if x.get("id") == video_id), None)
        if not v:
            time.sleep(10)
            continue
        status = v.get("output_status") or ""
        if status != last_status:
            print(f"  … video {video_id} → {status} ({v.get('note', '')[:80]})", flush=True)
            last_status = status
        if status in ("待交付", "已交付"):
            return v
        if status == "失败":
            raise RuntimeError(v.get("fail_reason") or v.get("note") or "video failed")
        time.sleep(15)
    raise TimeoutError(f"video timeout ({timeout_sec}s), last={last_status}")


def poll_scripts(client: httpx.Client, batch_id: str, timeout_sec: int = 300) -> dict:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        scripts = client.get(f"{BASE}/api/scripts", params={"batch_id": batch_id}, timeout=30).json()
        if not scripts:
            time.sleep(5)
            continue
        statuses = {s.get("review_status") for s in scripts}
        if "失败" in statuses:
            failed = next(s for s in scripts if s.get("review_status") == "失败")
            raise RuntimeError(failed.get("review_note", "")[:300])
        if statuses <= {"待审核"}:
            return scripts[0]
        if statuses <= {"排队中", "生成中"}:
            time.sleep(8)
            continue
        if any(s.get("review_status") == "待审核" for s in scripts):
            return next(s for s in scripts if s.get("review_status") == "待审核")
        time.sleep(8)
    raise TimeoutError("script generation timeout")


def run_p4(client: httpx.Client, ctx: dict) -> dict:
    prompt_id = ctx.get("prompt_id", "")
    if not prompt_id:
        log("P4.0 load context", False, "missing prompt_id")
        return {}
    video_id = f"V{prompt_id}"

    videos = client.get(f"{BASE}/api/videos", timeout=30).json()
    existing = next((v for v in videos if v.get("id") == video_id), None)
    if existing and existing.get("output_status") in ("待交付", "已交付"):
        log("P4.2 video generation", True, f"already {existing.get('output_status')}")
        log("P4.2a video_url present", bool(existing.get("video_url")), (existing.get("video_url") or "")[:80])
        log("P4.2b subtitle_status", True, existing.get("subtitle_status", ""))
        prompt_full = client.get(f"{BASE}/api/prompts/{prompt_id}", timeout=30).json()
        spec = json.loads(prompt_full.get("product_spec_json") or "{}")
        pu = spec.get("product_understanding") or {}
        log("P4.3 brand in final spec", pu.get("brand") == "BLUETTI", str(pu.get("brand")))
        return {"video_id": video_id, "video": existing}

    prompt = client.get(f"{BASE}/api/prompts/{prompt_id}", timeout=30).json()
    if prompt.get("review_status") == "待审核":
        rev = client.post(
            f"{BASE}/api/prompts/{prompt_id}/review",
            json={"status": "通过", "note": "Test plan P4 approve"},
            timeout=30,
        )
        log("P4.1 review_prompt approve", rev.status_code == 200, f"prompt_id={prompt_id}")
    else:
        log("P4.1 review_prompt approve", True, f"already {prompt.get('review_status')}")

    print("… waiting for Seedance video (up to 30 min) …", flush=True)
    try:
        video = poll_video(client, video_id, timeout_sec=1800)
    except Exception as e:
        log("P4.2 video generation", False, str(e))
        return {}

    has_url = bool((video.get("video_url") or "").strip())
    log("P4.2 video generation", video.get("output_status") == "待交付", video.get("output_status", ""))
    log("P4.2a video_url present", has_url, (video.get("video_url") or "")[:80])
    log("P4.2b subtitle_status", video.get("subtitle_status") in ("已完成", "跳过", ""), video.get("subtitle_status", ""))

    spec = {}
    try:
        prompt_full = client.get(f"{BASE}/api/prompts/{prompt_id}", timeout=30).json()
        spec = json.loads(prompt_full.get("product_spec_json") or "{}")
    except json.JSONDecodeError:
        pass
    pu = spec.get("product_understanding") or {}
    log("P4.3 brand in final spec", pu.get("brand") == "BLUETTI", str(pu.get("brand")))
    return {"video_id": video_id, "video": video}


def run_p5(client: httpx.Client, anker_id: str, direction: str) -> None:
    """Backend autopilot: auto-approve script+prompt and generate one video."""
    print("… P5 autopilot batch (Anker, count=1) …", flush=True)
    cr = client.post(
        f"{BASE}/api/batches/autopilot",
        json={
            "product": anker_id,
            "direction": direction,
            "count": 1,
            "language": "英语",
            "difficulty_level": "低级",
            "extra_instruction": "P5 autopilot smoke: home backup scene only.",
        },
        timeout=30,
    )
    if cr.status_code >= 400:
        log("P5.1 autopilot create_batch", False, cr.text[:200])
        return
    batch_id = cr.json().get("batch_id", "")
    log("P5.1 autopilot create_batch", bool(batch_id), f"batch_id={batch_id}")

    deadline = time.time() + 2400
    video_id = ""
    while time.time() < deadline:
        scripts = client.get(f"{BASE}/api/scripts", params={"batch_id": batch_id}, timeout=30).json()
        prompts = client.get(f"{BASE}/api/prompts", timeout=30).json()
        pids = {s["id"] for s in scripts}
        batch_prompts = [p for p in prompts if p.get("script_id") in pids]
        videos = client.get(f"{BASE}/api/videos", timeout=30).json()
        batch_videos = [v for v in videos if v.get("script_id") in pids]

        if batch_videos:
            v = batch_videos[0]
            video_id = v["id"]
            st = v.get("output_status", "")
            if st in ("待交付", "已交付"):
                log("P5.2 autopilot video done", True, f"video_id={video_id}")
                log("P5.2a video_url", bool(v.get("video_url")), (v.get("video_url") or "")[:60])
                return
            if st == "失败":
                log("P5.2 autopilot video done", False, v.get("fail_reason", "")[:200])
                return
        elif batch_prompts and all(p.get("review_status") == "通过" for p in batch_prompts):
            print(f"  … prompt approved, waiting video …", flush=True)
        elif scripts and all(s.get("review_status") == "通过" for s in scripts):
            print(f"  … scripts approved, waiting prompt …", flush=True)
        elif scripts:
            st = {s.get("review_status") for s in scripts}
            print(f"  … scripts {st} …", flush=True)
        time.sleep(20)
    log("P5.2 autopilot video done", False, "timeout 40min")


def run_p6(client: httpx.Client, direction: str, image_url: str) -> None:
    """Empty-brand product: script must not inject BLUETTI."""
    SPECS = """【型号】Neutral Test Unit 100
【外观】Plain gray box with LCD, no brand logo visible.
【演示规则】Show LCD only. NO plugs, NO outlets.
【禁止】插插座、品牌特写
"""
    body = {
        "name": "_plan_test Neutral",
        "brand": "",
        "brand_pronunciation": "",
        "image_urls": [image_url],
        "product_specs": SPECS,
        "selling_points": "Compact backup power for camping.",
        "product_specs_confirmed": True,
    }
    r = client.post(f"{BASE}/api/products", json=body, timeout=60)
    if r.status_code >= 400:
        log("P6.1 create neutral product", False, r.text[:200])
        return
    pid = r.json()["id"]
    prod = client.get(f"{BASE}/api/products/{pid}", timeout=30).json()
    log(
        "P6.1 create neutral product",
        not (prod.get("brand") or "").strip(),
        f"id={pid}",
    )

    cr = client.post(
        f"{BASE}/api/batches",
        json={
            "product": pid,
            "direction": direction,
            "count": 1,
            "language": "英语",
            "difficulty_level": "低级",
        },
        timeout=30,
    )
    if cr.status_code >= 400:
        log("P6.2 neutral batch", False, cr.text[:200])
        client.delete(f"{BASE}/api/products/{pid}", timeout=15)
        return
    batch_id = cr.json()["batch_id"]
    log("P6.2 neutral batch", True, batch_id)

    print("… P6 waiting for neutral script …", flush=True)
    try:
        script_summary = poll_scripts(client, batch_id, timeout_sec=300)
    except Exception as e:
        log("P6.3 neutral script", False, str(e))
        client.delete(f"{BASE}/api/products/{pid}", timeout=15)
        return

    script = client.get(f"{BASE}/api/scripts/{script_summary['id']}", timeout=30).json()
    blob = json.dumps(script, ensure_ascii=False).lower()
    no_bluetti = "bluetti" not in blob
    log("P6.3 neutral script generated", script.get("review_status") == "待审核", script_summary["id"])
    log("P6.3a no BLUETTI leak", no_bluetti, script.get("theme", "")[:60])
    client.delete(f"{BASE}/api/products/{pid}", timeout=15)


def main() -> int:
    ctx = load_ctx()
    meta = httpx.get(f"{BASE}/api/meta", timeout=30).json()
    direction = (meta.get("directions") or [{}])[0].get("name", "⑤功能解说型")

    with httpx.Client() as client:
        h = client.get(f"{BASE}/health", timeout=10)
        log("P4.0 backend health", h.status_code == 200)

        p4 = run_p4(client, ctx)
        if p4:
            ctx.update(p4)
            (ROOT / "data" / "_test_plan_result.json").write_text(
                json.dumps(ctx, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

        anker_id = (ctx.get("products") or [None])[0]
        if anker_id:
            run_p5(client, anker_id, direction)
        else:
            log("P5 skip", False, "no anker product id in context")

        # reuse last uploaded image from BLUETTI product
        image_url = ""
        blu_id = (ctx.get("products") or [None, None])[1] if len(ctx.get("products") or []) > 1 else ""
        if blu_id:
            p = client.get(f"{BASE}/api/products/{blu_id}", timeout=15).json()
            urls = json.loads(p.get("image_urls_json") or "[]")
            image_url = urls[0] if urls else p.get("image_url", "")
        if image_url:
            run_p6(client, direction, image_url)
        else:
            log("P6 skip", False, "no image url")

    failed = [n for n, ok, _ in LOG if not ok]
    print("---")
    print(f"SUMMARY: {len(LOG) - len(failed)} / {len(LOG)} passed")
    if failed:
        print("FAILED:", ", ".join(failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
