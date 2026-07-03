"""将分镜结构化数据编译为 Seedance 两段视频 prompt。"""

from __future__ import annotations

import re
from typing import Any, Literal

_PART_A_END = 15
_SKELETON_MAX_LEN = 280
_SKELETON_PATTERNS = (
    re.compile(r"^0-15s:\s*0-3s attention grab", re.I),
    re.compile(r"^15-30s:\s*resolve suspense", re.I),
    re.compile(r"→.*→"),  # 仅流程箭头、无镜头描述
)


def _beat_start_sec(time_str: str) -> int:
    m = re.match(r"(\d+)", (time_str or "").strip())
    return int(m.group(1)) if m else 0


def beats_for_part(beats: list[dict[str, Any]], part: Literal["a", "b"]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for beat in beats:
        start = _beat_start_sec(str(beat.get("time", "")))
        if part == "a" and start < _PART_A_END:
            out.append(beat)
        elif part == "b" and start >= _PART_A_END:
            out.append(beat)
    return out


def is_skeleton_prompt(text: str) -> bool:
    """LLM 是否只输出了 storyboard_system 示例里的占位骨架。"""
    t = (text or "").strip()
    if not t:
        return True
    if len(t) <= _SKELETON_MAX_LEN and any(p.search(t) for p in _SKELETON_PATTERNS):
        return True
    # 过短且缺少镜头/场景关键词 → 视为未展开
    if len(t) < 180:
        keywords = ("shot", "camera", "scene", "close-up", "wide", "beat", "镜头", "场景")
        if not any(k in t.lower() for k in keywords):
            return True
    return False


def _voice_line(spec: dict[str, Any], fallback: str = "") -> str:
    profile = spec.get("voice_profile") or {}
    raw = (
        (profile.get("prompt_hint") or "").strip()
        or (profile.get("seedance_hint") or "").strip()
        or fallback.strip()
    )
    if raw.lower().startswith("voice:"):
        return raw.split(":", 1)[1].strip()
    return raw


def _spoken_map(voiceovers: list[dict[str, Any]]) -> dict[str, str]:
    return {str(v.get("time", "")).strip(): str(v.get("spoken") or v.get("voiceover") or "").strip() for v in voiceovers}


def compile_seedance_segment_prompt(
    *,
    part: Literal["a", "b"],
    spec: dict[str, Any],
    product_name: str = "",
    voice_profile_hint: str = "",
    visual_only: bool = False,
) -> str:
    """把 interaction_beats + 口播表编译成单段 15s 英文视频 prompt。"""
    beats = beats_for_part(spec.get("interaction_beats") or [], part)
    vo_key = "voiceover_part_a" if part == "a" else "voiceover_part_b"
    voiceovers: list[dict[str, Any]] = spec.get(vo_key) or []
    spoken_by_time = _spoken_map(voiceovers)

    lines: list[str] = []
    if not visual_only:
        voice = _voice_line(spec, voice_profile_hint)
        if voice:
            lines.append(f"Voice: {voice}")

    pu = spec.get("product_understanding") or {}
    hero = (pu.get("hero_product") or product_name or "").strip()
    appearance = (pu.get("appearance_notes") or "").strip()
    modules = pu.get("allowed_modules") or []
    module_count = pu.get("module_count")
    bw = f"{str(pu.get('brand')).strip()} " if str(pu.get("brand") or "").strip() else ""
    if modules or module_count:
        mod_line = (
            f"KIT WHITELIST: show EXACTLY {module_count or len(modules)} {bw}module(s) only — "
            + ", ".join(str(m) for m in modules)
            + f". NO extra {bw}power stations, batteries, solar panels, or accessory modules."
        )
        lines.append(mod_line)
    if hero or appearance:
        desc = f"Hero product: {hero}." if hero else "Hero product on screen."
        if appearance:
            desc += f" {appearance}"
        lines.append(desc.strip())
    acc = pu.get("allowed_accessories") or []
    if acc and not modules:
        lines.append(
            "Accessories allowed (only these): " + ", ".join(str(a) for a in acc) + "."
        )

    arc = spec.get("narrative_arc") or {}
    if not visual_only:
        if part == "a":
            arc_hint = (
                f"Narrative arc: Hook (0-3s) → selling points (3-12s) → suspense cliffhanger (12-15s, do not resolve). "
                f"Suspense line: {arc.get('suspense_hook_12_15s', '')}"
            ).strip()
        else:
            arc_hint = (
                f"Narrative arc: Resolve suspense (15-18s) → demo (18-24s) → wrap-up (24-27s) → CTA (27-30s). "
                f"Payoff: {arc.get('payoff_15_30s', '')}"
            ).strip()
        if arc_hint:
            lines.append(arc_hint)

    seg_label = "0-15s" if part == "a" else "15-30s"
    lines.append(
        f"Segment {seg_label} · vertical 9:16 · ONE continuous main scene · max 2 held camera beats (5-8s each) · "
        "no plug-in/outlet shots · no readable on-screen text/subtitles (icon stickers like arrows OK):"
    )

    if beats:
        for i, beat in enumerate(beats, 1):
            t = str(beat.get("time", "")).strip()
            camera = str(beat.get("camera", "")).strip()
            action = str(beat.get("action", "")).strip()
            vo = str(beat.get("voiceover", "")).strip() or spoken_by_time.get(t, "")
            chunk = f"Beat {i} ({t}):"
            if camera:
                chunk += f" Camera: {camera}."
            if action:
                chunk += f" Action: {action}."
            if vo and not visual_only:
                chunk += f' Voiceover: "{vo}"'
            lines.append(chunk)
    elif voiceovers and not visual_only:
        for vo in voiceovers:
            t = str(vo.get("time", "")).strip()
            spoken = str(vo.get("spoken") or vo.get("voiceover") or "").strip()
            phase = str(vo.get("phase", "")).strip()
            label = f"{t} ({phase})" if phase else t
            lines.append(f'{label} Voiceover: "{spoken}"')

    forbidden = pu.get("forbidden_in_frame") or []
    if forbidden:
        lines.append("Do NOT show: " + "; ".join(str(x) for x in forbidden[:6]))

    return "\n\n".join(lines).strip()


def _is_viral_15s_prompt(text: str) -> bool:
    t = (text or "").lower()
    return "[0-3s" in t and ("[3-10s" in t or "[3-10s core]" in t)


def compile_ugc_viral_15s_prompt(
    *,
    spec: dict[str, Any],
    product_name: str = "",
    voice_profile_hint: str = "",
) -> str:
    """PopSmilz 15s native: [0-3s Hook][3-10s Core][10-15s CTA] + embedded Voiceover."""
    beats: list[dict[str, Any]] = spec.get("interaction_beats") or []
    voiceovers: list[dict[str, Any]] = spec.get("voiceover_part_a") or []
    spoken_by_time = _spoken_map(voiceovers)

    pu = spec.get("product_understanding") or {}
    hero = (pu.get("hero_product") or product_name or "").strip() or "hero product on screen"
    appearance = (pu.get("appearance_notes") or "").strip()

    sections: list[str] = []
    for label, time_key in (("Hook", "0-3"), ("Core", "3-10"), ("CTA", "10-15")):
        beat = next(
            (b for b in beats if time_key in str(b.get("time", ""))),
            {},
        )
        t = str(beat.get("time", f"{time_key}s")).strip()
        camera = str(beat.get("camera", "")).strip()
        action = str(beat.get("action", "")).strip()
        vo = (
            str(beat.get("voiceover", "")).strip()
            or spoken_by_time.get(t, "")
            or spoken_by_time.get(f"{time_key}s", "")
        )
        scene_bits = [camera, action]
        scene = ". ".join(x for x in scene_bits if x)
        if not scene:
            scene = "Handheld smartphone UGC, natural lighting, Gen-Z creator energy."
        prefix = "High-energy UGC TikTok video."
        if label == "Core" and hero:
            prefix += f" Hero: {hero}."
            if appearance:
                prefix += f" {appearance}"
        line = f"[{time_key}s {label}] {prefix} {scene}"
        if vo:
            line += f' [Voiceover: "{vo}"]'
        sections.append(line.strip())

    profile = spec.get("voice_profile") or {}
    voice = _voice_line(spec, voice_profile_hint)
    if voice:
        sections.insert(0, f"Voice: {voice}")

    forbidden = pu.get("forbidden_in_frame") or []
    extra = [
        "TikTok logo",
        "platform watermark",
        "readable burned subtitles",
        "popcorn",
        "stiff AI face",
    ]
    merged = list(dict.fromkeys([*(str(x) for x in forbidden), *extra]))
    sections.append("Do NOT show: " + "; ".join(merged[:8]))
    return "\n\n".join(sections).strip()


def resolve_segment_prompt(
    *,
    part: Literal["a", "b"],
    llm_text: str,
    spec: dict[str, Any],
    product_name: str = "",
    voice_profile_hint: str = "",
    visual_only: bool = False,
    native_ugc_15s: bool = False,
) -> str:
    """优先用 LLM 完整分镜；若为占位骨架则从 structured spec 编译。"""
    if native_ugc_15s and part == "a":
        text = (llm_text or "").strip()
        viral = compile_ugc_viral_15s_prompt(
            spec=spec,
            product_name=product_name,
            voice_profile_hint=voice_profile_hint,
        )
        if _is_viral_15s_prompt(text):
            return text
        if viral and (is_skeleton_prompt(text) or len(text) < len(viral) * 0.55):
            return viral
        if text:
            return text
        return viral

    compiled = compile_seedance_segment_prompt(
        part=part,
        spec=spec,
        product_name=product_name,
        voice_profile_hint=voice_profile_hint,
        visual_only=visual_only,
    )
    text = (llm_text or "").strip()
    if is_skeleton_prompt(text):
        return compiled
    if compiled and len(text) < len(compiled) * 0.6:
        # LLM 文本明显短于结构化编译结果 → 用编译版
        return compiled
    return text
