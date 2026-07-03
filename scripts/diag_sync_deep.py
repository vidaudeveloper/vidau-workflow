"""深度音画同步诊断 — python scripts/diag_sync_deep.py [video_id]"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.db.repository import Repository
from src.pipeline.subtitle_align import (
    _prepare_wav,
    _transcribe_words_local,
    align_voiceover_to_video,
    collect_blocks_with_spoken,
)
from src.pipeline.subtitles import collect_heuristic_events, caption_source_text


def main() -> None:
    repo = Repository()
    vid = sys.argv[1] if len(sys.argv) > 1 else repo.list_videos()[0]["id"]
    v = repo.get_video(vid)
    p = repo.get_prompt(v.get("prompt_id", ""))
    spec = json.loads((p or {}).get("product_spec_json") or "{}")
    vo_a = spec.get("voiceover_part_a", [])
    vo_b = spec.get("voiceover_part_b", [])

    raw = ROOT / "data/uploads/videos" / f"{vid}.mp4"
    print(f"=== {vid} ===")
    print("align:", v.get("subtitle_align_status"), "|", (v.get("subtitle_align_detail") or "")[:120])

    fb = collect_heuristic_events(vo_a, vo_b)
    res = align_voiceover_to_video(vo_a, vo_b, raw, fallback_events=fb)

    tmp, wav = _prepare_wav(raw)
    with tmp:
        asr = _transcribe_words_local(wav)

    print(f"\nASR words: {len(asr)}  |  Aligned cues: {len(res.events)}  |  Blocks: {len(collect_blocks_with_spoken(vo_a, vo_b))}")
    print(f"Mode: {res.timing_mode} / {res.align_status}")

    # 15s 接缝
    near_15 = [w for w in asr if 13.5 <= w.start <= 16.5]
    print(f"\n--- ASR around 15s concat seam ({len(near_15)} words) ---")
    for w in near_15:
        print(f"  {w.start:6.2f}-{w.end:6.2f}  {w.word}")

    # 最大漂移
    print("\n--- Largest timing drift (aligned vs heuristic script time) ---")
    drifts = []
    for i, (a, b) in enumerate(zip(fb, res.events)):
        if a[2] != b[2]:
            continue
        drifts.append((i, b[0] - a[0], b[1] - a[1], a[2].replace("\\N", " | ")[:55]))
    drifts.sort(key=lambda x: max(abs(x[1]), abs(x[2])), reverse=True)
    for i, ds, de, txt in drifts[:8]:
        print(f"  [{i:2d}] start {ds:+.2f}s  end {de:+.2f}s  | {txt}")

    # 词级：每块首词 ASR 时间 vs 字幕开始
    blocks = collect_blocks_with_spoken(vo_a, vo_b)
    print("\n--- First spoken word ASR time vs subtitle start ---")
    asr_idx = 0
    for i, (ev, blk) in enumerate(zip(res.events, blocks)):
        words = blk.get("spoken_words") or []
        if not words:
            continue
        target = words[0].lower().strip(".,!?")
        found = None
        for j in range(asr_idx, min(asr_idx + 20, len(asr))):
            heard = asr[j].word.lower().strip(".,!?")
            if target[:4] == heard[:4] or target in heard or heard in target:
                found = asr[j]
                asr_idx = j
                break
        if found:
            delta = ev[0] - found.start
            flag = " ***" if abs(delta) > 0.8 else ""
            print(f"  [{i:2d}] sub@{ev[0]:5.2f}s  asr@{found.start:5.2f}s  delta={delta:+.2f}s{flag}  | {words[0][:20]}")
        else:
            print(f"  [{i:2d}] sub@{ev[0]:5.2f}s  asr@?       | {words[0][:20]}")

    print("\n--- Voiceover time windows vs actual speech clusters ---")
    for item in vo_a + vo_b:
        t = item.get("time", "")
        spoken = caption_source_text(item)[:60]
        parts = t.replace("s", "").split("-")
        if len(parts) == 2:
            w0, w1 = float(parts[0]), float(parts[1])
            in_win = [w for w in asr if w.end > w0 and w.start < w1]
            if in_win:
                actual_start, actual_end = in_win[0].start, in_win[-1].end
                print(f"  {t:8s} script [{w0:.0f}-{w1:.0f}s]  actual [{actual_start:.1f}-{actual_end:.1f}s]  drift={actual_start-w0:+.1f}s  | {spoken}")


if __name__ == "__main__":
    main()
