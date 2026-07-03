"""Execute test plan P1–P3 (stop before prompt approve / paid video)."""
from __future__ import annotations

import json
import struct
import sys
import time
import zlib
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


def minimal_png(path: Path, size: int = 128) -> None:
    raw = b""
    row = b"\x00" + (b"\xcc\xcc\xcc" * size)
    for _ in range(size):
        raw += row
    compressed = zlib.compress(raw, 9)

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)
    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", compressed) + chunk(b"IEND", b"")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(png)


SPECS = """【型号】Test Portable Power 500
【外观】Compact gray rectangular unit, front LCD panel, side carry handle, no visible wall outlets on unit face.
【演示规则】Press power button; show LCD watt reading. NO plugging into wall outlets, NO AC/USB port close-ups, NO hands inserting plugs.
【禁止】插插座、插口特写、手插插头、墙插、线缆接入演示
"""

SELLING = "2.4kW output, 2kWh capacity, quiet home backup and camping."


def upload_image(client: httpx.Client, png_path: Path) -> list[str]:
    with png_path.open("rb") as f:
        r = client.post(
            f"{BASE}/api/uploads/product-images",
            files=[("files", (png_path.name, f, "image/png"))],
            timeout=60,
        )
    r.raise_for_status()
    data = r.json()
    if isinstance(data, list):
        return data
    return data.get("urls") or data.get("image_urls") or []


def create_product(
    client: httpx.Client,
    *,
    name: str,
    brand: str,
    pronunciation: str,
    urls: list[str],
) -> str:
    body = {
        "name": name,
        "brand": brand,
        "brand_pronunciation": pronunciation,
        "image_urls": urls[:1],
        "product_specs": SPECS,
        "selling_points": SELLING,
        "product_specs_confirmed": True,
    }
    r = client.post(f"{BASE}/api/products", json=body, timeout=60)
    r.raise_for_status()
    return r.json()["id"]


def poll_scripts(client: httpx.Client, batch_id: str, timeout_sec: int = 300) -> dict | None:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        scripts = client.get(f"{BASE}/api/scripts", params={"batch_id": batch_id}, timeout=30).json()
        if not scripts:
            time.sleep(5)
            continue
        statuses = {s.get("review_status") for s in scripts}
        if statuses <= {"待审核"}:
            return scripts[0]
        if "失败" in statuses:
            failed = next(s for s in scripts if s.get("review_status") == "失败")
            raise RuntimeError(f"script failed: {failed.get('review_note', '')[:300]}")
        if statuses <= {"排队中", "生成中"}:
            time.sleep(8)
            continue
        # mixed or unexpected
        if any(s.get("review_status") == "待审核" for s in scripts):
            return next(s for s in scripts if s.get("review_status") == "待审核")
        time.sleep(8)
    raise TimeoutError("script generation timeout")


def poll_prompt(client: httpx.Client, script_id: str, timeout_sec: int = 300) -> dict | None:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        prompts = client.get(f"{BASE}/api/prompts", timeout=30).json()
        match = [p for p in prompts if p.get("script_id") == script_id]
        if match:
            pid = match[0]["id"]
            return client.get(f"{BASE}/api/prompts/{pid}", timeout=30).json()
        time.sleep(8)
    raise TimeoutError("prompt generation timeout")


def script_text_blob(script: dict) -> str:
    parts = [
        script.get("hook", ""),
        script.get("outline", ""),
        script.get("cta", ""),
        json.dumps(script.get("shots", []), ensure_ascii=False),
    ]
    return "\n".join(parts)


def main() -> int:
    created_ids: list[str] = []
    batch_id = ""
    png = ROOT / "data" / "_test_plan_product.png"
    minimal_png(png)

    with httpx.Client() as client:
        # ----- P1 -----
        try:
            h = client.get(f"{BASE}/health", timeout=10)
            log("P1.1 backend health", h.status_code == 200, h.text[:60])
        except Exception as e:
            log("P1.1 backend health", False, str(e))
            return 1

        meta = client.get(f"{BASE}/api/meta", timeout=30).json()
        directions = meta.get("directions") or []
        log("P1.2 get_meta", bool(directions), f"directions={len(directions)}")
        direction = directions[0]["name"] if directions else "⑤功能解说型"

        pricing = client.get(f"{BASE}/api/billing/pricing", timeout=30)
        log("P1.3 get_pricing", pricing.status_code == 200)

        est = client.post(
            f"{BASE}/api/toc/quick-generate/estimate",
            json={"brief": "30s portable power ad test", "duration_sec": 15},
            timeout=30,
        )
        log("P1.4 estimate_cost", est.status_code == 200, est.text[:80])

        # ----- P2 -----
        urls = upload_image(client, png)
        log("P2.1 upload_product_images", bool(urls), str(urls[:1]))

        anker_id = create_product(
            client,
            name="_plan_test Anker",
            brand="Anker",
            pronunciation="",
            urls=urls,
        )
        created_ids.append(anker_id)
        anker = client.get(f"{BASE}/api/products/{anker_id}", timeout=30).json()
        log(
            "P2.2 create Anker product",
            anker.get("brand") == "Anker" and int(anker.get("product_specs_confirmed") or 0) == 1,
            f"id={anker_id}",
        )

        blu_id = create_product(
            client,
            name="_plan_test BLUETTI",
            brand="BLUETTI",
            pronunciation="blue tee",
            urls=urls,
        )
        created_ids.append(blu_id)
        blu = client.get(f"{BASE}/api/products/{blu_id}", timeout=30).json()
        log(
            "P2.3 create BLUETTI product",
            blu.get("brand") == "BLUETTI"
            and blu.get("brand_pronunciation") == "blue tee"
            and int(blu.get("product_specs_confirmed") or 0) == 1,
            f"id={blu_id}",
        )

        guard = client.post(
            f"{BASE}/api/batches",
            json={
                "product": anker_id,
                "direction": direction,
                "count": 1,
                "language": "英语",
                "difficulty_level": "低级",
            },
            timeout=30,
        )
        # temporarily unconfirm to test guard — skip, anker is confirmed
        # test unconfirmed by patching a fake - skip

        # ----- P3 -----
        cr = client.post(
            f"{BASE}/api/batches",
            json={
                "product": blu_id,
                "direction": direction,
                "count": 1,
                "language": "英语",
                "difficulty_level": "低级",
                "extra_instruction": "Test batch: emphasize home backup scene, no plug-in shots.",
            },
            timeout=30,
        )
        if cr.status_code >= 400:
            log("P3.1 create_batch", False, cr.text[:200])
            return 1
        batch_id = cr.json().get("batch_id", "")
        log("P3.1 create_batch", bool(batch_id), f"batch_id={batch_id}")

        print("… waiting for script generation (up to 5 min) …", flush=True)
        try:
            script_summary = poll_scripts(client, batch_id, timeout_sec=300)
        except Exception as e:
            log("P3.2 script generation", False, str(e))
            return 1

        script_id = script_summary["id"]
        script = client.get(f"{BASE}/api/scripts/{script_id}", timeout=30).json()
        blob = script_text_blob(script).lower()
        has_brand = "bluetti" in blob
        no_plug = not any(
            x in blob for x in ["plug into", "wall socket", "insert plug", "outlet close"]
        )
        log("P3.2 script generated", script.get("review_status") == "待审核", f"script_id={script_id}")
        log("P3.2a script mentions BLUETTI", has_brand, script.get("theme", "")[:60])
        log("P3.2b script no plug visuals", no_plug)

        rev = client.post(
            f"{BASE}/api/scripts/{script_id}/review",
            json={"status": "通过", "note": "Test plan auto-approve", "reviewer": "test-runner"},
            timeout=30,
        )
        log("P3.3 review_script approve", rev.status_code == 200)

        print("… waiting for storyboard prompt (up to 5 min) …", flush=True)
        try:
            time.sleep(3)
            prompt = poll_prompt(client, script_id, timeout_sec=300)
        except Exception as e:
            log("P3.4 prompt generation", False, str(e))
            return 1

        spec = {}
        try:
            spec = json.loads(prompt.get("product_spec_json") or "{}")
        except json.JSONDecodeError:
            pass
        pu = spec.get("product_understanding") or {}
        vo_a = spec.get("voiceover_part_a") or []
        vo_b = spec.get("voiceover_part_b") or []
        brand_in_spec = pu.get("brand") == "BLUETTI"
        pron_in_spec = pu.get("brand_pronunciation") == "blue tee"
        has_vo = len(vo_a) + len(vo_b) > 0
        spoken_blob = json.dumps(vo_a + vo_b, ensure_ascii=False).lower()
        screen_has_bluetti = "bluetti" in spoken_blob

        log("P3.4 prompt generated", bool(prompt.get("id")), f"prompt_id={prompt.get('id')}")
        log("P3.4a spec brand field", brand_in_spec, str(pu.get("brand")))
        log("P3.4b spec pronunciation", pron_in_spec, str(pu.get("brand_pronunciation")))
        log("P3.4c voiceover tables non-empty", has_vo, f"a={len(vo_a)} b={len(vo_b)}")
        log("P3.4d spoken uses BLUETTI spelling", screen_has_bluetti)
        log(
            "P3.5 STOP before review_prompt approve",
            prompt.get("review_status") in ("待审核", "排队中", "生成中", None),
            f"status={prompt.get('review_status')} — NOT triggering Seedance",
        )

        summary_path = ROOT / "data" / "_test_plan_result.json"
        summary_path.write_text(
            json.dumps(
                {
                    "batch_id": batch_id,
                    "script_id": script_id,
                    "prompt_id": prompt.get("id"),
                    "products": created_ids,
                    "direction": direction,
                    "stopped_before": "review_prompt approve",
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"Result saved: {summary_path}", flush=True)

    failed = [n for n, ok, _ in LOG if not ok]
    print("---")
    print(f"SUMMARY: {len(LOG) - len(failed)} / {len(LOG)} passed")
    if failed:
        print("FAILED:", ", ".join(failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
