"""对已有成片跑 TTS 后期 + 烧字幕 — python scripts/tts_post_one.py [video_id]"""

import asyncio
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.db.repository import Repository
from src.pipeline.subtitles import burn_subtitles_on_video, raw_video_path, resolve_burn_input_path
from src.pipeline.tts_post import apply_tts_post_production
from src.pipeline.voice_persona import build_voice_profile


async def main() -> None:
    repo = Repository()
    videos = repo.list_videos()
    if not videos:
        print("无视频记录")
        return
    vid = sys.argv[1] if len(sys.argv) > 1 else videos[0]["id"]
    video = repo.get_video(vid)
    if not video:
        print(f"视频不存在: {vid}")
        return
    prompt = repo.get_prompt(video.get("prompt_id", ""))
    if not prompt:
        print("无关联 prompt")
        return

    spec = json.loads(prompt.get("product_spec_json") or "{}")
    vo_a = spec.get("voiceover_part_a", [])
    vo_b = spec.get("voiceover_part_b", [])
    voice_persona = spec.get("voice_profile") or {}
    script = repo.get_script(prompt.get("script_id", ""))
    acc = repo.get_account(script.get("account_id", "")) if script else None
    if not voice_persona:
        voice_persona = build_voice_profile(acc)
    elif not voice_persona.get("tts_voice"):
        from src.pipeline.voice_persona import resolve_tts_voice

        voice_persona = dict(voice_persona)
        voice_persona["tts_voice"] = resolve_tts_voice(voice_persona, account=acc)
    acc_id = script.get("account_id", "") if script else ""

    raw = raw_video_path(vid)
    if not raw.is_file():
        sub_src = resolve_burn_input_path(vid, None)
        if "_sub" in sub_src.name:
            backup = raw_video_path(vid)
            shutil.copy2(sub_src, backup)
            print(f"从字幕片恢复无字幕源: {backup}")
        else:
            print(f"找不到源片: {raw}")
            return

    print(f"=== TTS 后期: {vid} ===")
    print(f"源片: {raw}")

    tts_result = await apply_tts_post_production(
        raw,
        vo_a,
        vo_b,
        voice_profile=voice_persona,
        account=acc,
        account_id=acc_id,
    )
    print(tts_result.detail)
    print(f"字幕条数: {len(tts_result.events)}")

    sub = await burn_subtitles_on_video(
        str(raw),
        voiceover_a=vo_a,
        voiceover_b=vo_b,
        video_id=vid,
        tts_events=tts_result.events,
        tts_detail=tts_result.detail,
    )
    print(f"输出: {sub.get('video_url')}")
    print(f"对齐: {sub.get('subtitle_align_status')} — {sub.get('subtitle_align_detail', '')[:120]}")

    repo.update_video(
        vid,
        {
            "video_url": sub["video_url"],
            "subtitle_status": "已完成",
            "subtitle_align_status": sub.get("subtitle_align_status", "TTS对齐"),
            "subtitle_align_detail": sub.get("subtitle_align_detail", tts_result.detail),
        },
    )
    print("DB 已更新")


if __name__ == "__main__":
    asyncio.run(main())
