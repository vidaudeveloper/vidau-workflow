#!/usr/bin/env python3
import argparse
import sys
import time

import httpx


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--base", default="https://adflow.vidau.info")
    p.add_argument("--batch-id", required=True)
    p.add_argument("--wait-min", type=int, default=90)
    args = p.parse_args()
    base = args.base.rstrip("/")
    bid = args.batch_id

    with httpx.Client(timeout=60) as c:
        pub = c.get(f"{base}/api/meta").json().get("public_base_url", base).rstrip("/")
        deadline = time.time() + args.wait_min * 60
        vids: list[dict] = []
        while time.time() < deadline:
            batches = {b["id"]: b for b in c.get(f"{base}/api/batches").json()}
            status = batches.get(bid, {}).get("status", "")
            sids = {s["id"] for s in c.get(f"{base}/api/scripts", params={"batch_id": bid}).json()}
            vids = [v for v in c.get(f"{base}/api/videos").json() if v.get("script_id") in sids]
            done = [v for v in vids if (v.get("video_url") or "").strip()]
            pending = sum(1 for v in vids if v.get("output_status") in ("生成中", "排队中"))
            print(f"status={status!r} done={len(done)}/{len(vids)} pending={pending}")
            if len(done) >= len(vids) and vids:
                break
            if status in ("生成失败", "失败") and pending == 0:
                break
            time.sleep(45)

        print("\n=== videos ===")
        for i, v in enumerate(vids, 1):
            url = (v.get("video_url") or "").strip()
            if url and not url.startswith("http"):
                url = f"{pub}{url}"
            print(f"{i}. {v.get('output_status')} | {v.get('theme', '')[:50]}")
            if url:
                print(f"   {url}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
