#!/usr/bin/env python3
"""重试批次内排队/失败的视频（Seedance 配置好后执行）。"""
from __future__ import annotations

import argparse
import sys

import httpx


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--base", default="https://adflow.vidau.info")
    p.add_argument("--batch-id", required=True)
    args = p.parse_args()
    base = args.base.rstrip("/")
    bid = args.batch_id

    with httpx.Client(timeout=60) as c:
        sids = {s["id"] for s in c.get(f"{base}/api/scripts", params={"batch_id": bid}).json()}
        vids = [v for v in c.get(f"{base}/api/videos").json() if v.get("script_id") in sids]
        retried = 0
        for v in vids:
            st = v.get("output_status") or ""
            if st in ("排队中", "失败") or not (v.get("video_url") or "").strip():
                vid = v["id"]
                r = c.post(f"{base}/api/videos/{vid}/retry")
                print(vid, r.status_code, r.text[:120] if r.status_code >= 400 else "queued")
                if r.status_code < 400:
                    retried += 1
        print(f"retried {retried}/{len(vids)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
