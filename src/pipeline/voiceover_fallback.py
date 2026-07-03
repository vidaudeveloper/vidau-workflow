"""口播表兜底 — 分镜 LLM 未输出 voiceover_part_a/b 时从脚本 shots 或 interaction_beats 回填。"""

from __future__ import annotations

import re
from typing import Any


def _parse_shot_time(time_str: str) -> tuple[float, float]:
    raw = (time_str or "0-3s").strip().lower().replace(" ", "")
    m = re.match(r"(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)s?", raw)
    if not m:
        return 0.0, 3.0
    return float(m.group(1)), float(m.group(2))


def _format_time_range(start: float, end: float) -> str:
    s = int(start) if start == int(start) else start
    e = int(end) if end == int(end) else end
    return f"{s}-{e}s"


def build_voiceover_from_shots(
    shots: list[dict[str, Any]],
    *,
    language: str | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    from src.pipeline.script_normalize import normalize_shots

    vo_a: list[dict[str, Any]] = []
    vo_b: list[dict[str, Any]] = []
    for shot in normalize_shots(shots):
        audio = (shot.get("audio") or "").strip()
        if not audio:
            continue
        start, end = _parse_shot_time(str(shot.get("time", "")))
        item = {
            "time": _format_time_range(start, end),
            "phase": shot.get("phase", ""),
            "spoken": audio,
        }
        if start < 15:
            vo_a.append(item)
        else:
            vo_b.append(item)
    return vo_a, vo_b


def build_voiceover_from_beats(
    beats: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    vo_a: list[dict[str, Any]] = []
    vo_b: list[dict[str, Any]] = []
    for beat in beats:
        spoken = (beat.get("spoken") or beat.get("voiceover") or "").strip()
        if not spoken:
            continue
        start, end = _parse_shot_time(str(beat.get("time", "")))
        item = {
            "time": _format_time_range(start, end),
            "phase": beat.get("phase", ""),
            "spoken": spoken,
        }
        if start < 15:
            vo_a.append(item)
        else:
            vo_b.append(item)
    return vo_a, vo_b


def ensure_storyboard_voiceover(
    result: dict[str, Any],
    script: dict[str, Any] | None,
) -> dict[str, Any]:
    """保证 voiceover_part_a/b 非空（TTS 后期必需）。"""
    out = dict(result)
    va = out.get("voiceover_part_a") or []
    vb = out.get("voiceover_part_b") or []
    if va or vb:
        return out

    beats = out.get("interaction_beats") or []
    if beats:
        va, vb = build_voiceover_from_beats(beats)
        if va or vb:
            out["voiceover_part_a"] = va
            out["voiceover_part_b"] = vb
            out["_voiceover_source"] = "interaction_beats"
            return out

    script = script or {}
    va, vb = build_voiceover_from_shots(
        script.get("shots") or [],
        language=script.get("language"),
    )
    if va or vb:
        out["voiceover_part_a"] = va
        out["voiceover_part_b"] = vb
        out["_voiceover_source"] = "script_shots"
    return out


def resolve_voiceover_tracks(
    spec: dict[str, Any],
    script: dict[str, Any] | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """从 product_spec 读取口播表，空时从脚本 shots 兜底（兼容历史成片）。"""
    vo_a = spec.get("voiceover_part_a") or []
    vo_b = spec.get("voiceover_part_b") or []
    if vo_a or vo_b:
        return vo_a, vo_b
    patched = ensure_storyboard_voiceover(spec, script)
    return patched.get("voiceover_part_a") or [], patched.get("voiceover_part_b") or []
