#!/usr/bin/env python3
"""打印送入 Seedance 的完整 prompt（示例）。"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.config import get_settings
from src.db.repository import Repository
from src.pipeline.orchestrator import WorkflowOrchestrator
from src.pipeline.video import build_seedance_prompt


def main() -> None:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 2
    r = Repository()
    orch = WorkflowOrchestrator(r)
    settings = get_settings()
    generate_audio = not (settings.tts_post_enabled and settings.tts_mute_seedance_audio)

    pending = [p for p in r.list_prompts() if p.get("review_status") == "待审核"]
    approved = [p for p in r.list_prompts() if p.get("review_status") == "通过"]
    candidates = pending[:n] if len(pending) >= n else approved[:n]
    if len(candidates) < n:
        candidates = r.list_prompts()[:n]

    for i, p in enumerate(candidates, 1):
        ctx = orch._prompt_video_context(p)
        full_a = build_seedance_prompt(
            ctx["part_a"],
            voiceover_script=ctx["vo_a"] if generate_audio else None,
            negative_prompt=ctx["negative"],
            voice_profile=ctx["voice_profile"] if generate_audio else "",
            generate_audio=generate_audio,
        )
        script = ctx.get("script") or {}
        print("=" * 70)
        print(f"#{i} {p['id']}")
        print(f"产品: {script.get('product', '?')} | 方向: {script.get('direction', '?')}")
        print(f"审核: {p.get('review_status')} | 参考图: {len(ctx['image_urls'])} 张")
        print("--- Part A → Seedance 完整 prompt ---")
        print(full_a)
        if ctx["part_b"]:
            full_b = build_seedance_prompt(
                ctx["part_b"],
                voiceover_script=ctx["vo_b"] if generate_audio else None,
                negative_prompt=ctx["negative"],
                voice_profile=ctx["voice_profile"] if generate_audio else "",
                generate_audio=generate_audio,
            )
            print("--- Part B → Seedance 完整 prompt ---")
            print(full_b)
        print()


if __name__ == "__main__":
    main()
