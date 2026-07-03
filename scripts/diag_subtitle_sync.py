"""诊断字幕与口播同步 — python scripts/diag_subtitle_sync.py [video_id]"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.db.repository import Repository
from src.pipeline.subtitle_align import (
    _detect_speech_regions,
    _prepare_wav,
    align_voiceover_to_video,
    collect_blocks_with_spoken,
)
from src.pipeline.subtitles import collect_heuristic_events


def main() -> None:
    repo = Repository()
    vid = sys.argv[1] if len(sys.argv) > 1 else ""
    if not vid:
        videos = repo.list_videos()
        vid = videos[0]["id"] if videos else ""
    if not vid:
        raise SystemExit("无视频记录")

    v = repo.get_video(vid)
    if not v:
        raise SystemExit(f"视频不存在: {vid}")
    p = repo.get_prompt(v.get("prompt_id", ""))
    spec = json.loads((p or {}).get("product_spec_json") or "{}")
    vo_a = spec.get("voiceover_part_a", [])
    vo_b = spec.get("voiceover_part_b", [])

    raw = ROOT / "data/uploads/videos" / f"{vid}.mp4"
    print(f"=== {vid} ===")
    print("align_status:", v.get("subtitle_align_status"))
    print("align_detail:", v.get("subtitle_align_detail"))
    print("raw:", raw.exists(), raw.stat().st_size if raw.exists() else 0)

    print("\n--- voiceover A ---")
    for item in vo_a:
        print(item)
    print("--- voiceover B ---")
    for item in vo_b:
        print(item)

    if not raw.is_file():
        return

    fb = collect_heuristic_events(vo_a, vo_b)
    print(f"\n--- heuristic ({len(fb)} cues) ---")
    for start, end, text in fb:
        line = text.replace("\\N", " | ")
        print(f"{start:6.2f}-{end:6.2f}  {line[:80]}")

    tmp, wav = _prepare_wav(raw)
    with tmp:
        regions = _detect_speech_regions(wav)
        print(f"\n--- speech regions ({len(regions)}) ---")
        for r in regions:
            print(f"  {r[0]:.2f} - {r[1]:.2f}  ({r[1]-r[0]:.1f}s)")

        blocks = collect_blocks_with_spoken(vo_a, vo_b)
        print(f"\n--- caption blocks ({len(blocks)}) ---")
        for i, b in enumerate(blocks):
            sw = " ".join(b.get("spoken_words") or [])
            disp = b["display"].replace("\\N", " | ")
            print(f"  [{i}] spoken=[{sw}] -> {disp[:70]}")

    res = align_voiceover_to_video(vo_a, vo_b, raw, fallback_events=fb)
    print(f"\n--- aligned: {res.align_status} / {res.timing_mode} ---")
    for start, end, text in res.events:
        line = text.replace("\\N", " | ")
        print(f"{start:6.2f}-{end:6.2f}  {line[:80]}")

    print("\n--- drift vs heuristic ---")
    for i, (a, b) in enumerate(zip(fb, res.events)):
        ds = b[0] - a[0]
        de = b[1] - a[1]
        flag = " ***" if abs(ds) > 1.0 or abs(de) > 1.0 else ""
        print(f"  [{i}] start {ds:+.2f}s  end {de:+.2f}s{flag}")


if __name__ == "__main__":
    main()
