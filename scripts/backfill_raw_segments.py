"""批量补救旧任务 Part A/B 无字幕原片。

用法：
  python scripts/backfill_raw_segments.py          # 全部待交付/已交付任务
  python scripts/backfill_raw_segments.py <video_id>  # 单条视频
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.db.database import init_db
from src.db.repository import Repository
from src.util.package_download import backfill_all_raw_segments, backfill_raw_segments_for_video


async def main() -> None:
    init_db()
    repo = Repository()
    if len(sys.argv) > 1:
        video_id = sys.argv[1].strip()
        video = repo.get_video(video_id)
        if not video:
            print(f"视频不存在: {video_id}")
            raise SystemExit(1)
        result = await backfill_raw_segments_for_video(video)
        print(f"{result['video_id']}: {result['status']} — {result.get('detail', '')}")
        if result.get("methods"):
            print("  methods:", result["methods"])
        raise SystemExit(0 if result["status"] == "ok" else 1)

    summary = await backfill_all_raw_segments()
    print(
        f"完成：成功 {summary['ok']} · 失败 {summary['failed']} · 跳过 {summary['skipped']}"
    )
    for item in summary["items"]:
        if item["status"] != "ok":
            print(f"  X {item['video_id']}: {item.get('detail', '')}")
    raise SystemExit(0 if summary["failed"] == 0 else 1)


if __name__ == "__main__":
    asyncio.run(main())
