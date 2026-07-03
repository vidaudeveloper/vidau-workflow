"""Seedance native vs TTS post-production — resolved from Workflow Blueprint only."""

from __future__ import annotations

from typing import Any

from src.config import Settings, get_settings
from src.pipeline.workflow_blueprint import WorkflowBlueprint

SUBTITLE_MODES = ("skip", "burn_in")


def normalize_subtitles(value: str | None) -> str:
    v = (value or "burn_in").strip().lower()
    return v if v in SUBTITLE_MODES else "burn_in"


def should_burn_subtitles(
    settings: Settings | None = None,
    *,
    blueprint: WorkflowBlueprint | None = None,
) -> bool:
    """Blueprint production.subtitles=burn_in → 出片后烧录字幕（原生/TTS 自动选对齐方式）。"""
    prod = blueprint.production if blueprint else None
    if prod:
        return normalize_subtitles(prod.subtitles) == "burn_in"
    settings = settings or get_settings()
    return bool(settings.tts_post_enabled)


def subtitle_mode_label(
    mode: str | None,
    *,
    native_audio: bool,
) -> str:
    m = normalize_subtitles(mode)
    if m == "skip":
        return "无字幕"
    if native_audio:
        return "烧录字幕（对齐 Seedance 原生口播 · Whisper）"
    return "烧录字幕（对齐后期 TTS 时间轴）"


def production_subtitle_options(*, native_audio: bool = True) -> list[dict[str, str]]:
    """供 UI / Hermes 展示的字幕方案选项。"""
    align = "Whisper 识别 Seedance 口播并对齐" if native_audio else "按 TTS 时间轴对齐"
    return [
        {
            "id": "skip",
            "label": "无字幕",
            "description": "成片不烧录字幕；适合平台自动字幕或后期自行处理。",
        },
        {
            "id": "burn_in",
            "label": "烧录英文字幕",
            "description": f"出片后自动烧录 ASS 字幕到画面；{align}。",
        },
    ]


def production_audio_subtitle_matrix() -> list[dict[str, Any]]:
    """音频 × 字幕组合说明（Agent 向用户解释用）。"""
    return [
        {
            "audio": {"tts": False, "seedance_native_audio": True},
            "subtitles": "skip",
            "summary": "Seedance 原生口播 · 无字幕（PopSmilz 15s 默认）",
        },
        {
            "audio": {"tts": False, "seedance_native_audio": True},
            "subtitles": "burn_in",
            "summary": "Seedance 原生口播 · 烧录字幕（Whisper 对齐口播）",
        },
        {
            "audio": {"tts": True, "seedance_native_audio": False},
            "subtitles": "burn_in",
            "summary": "画面无声 · Edge TTS 配音 · 烧录字幕",
        },
        {
            "audio": {"tts": True, "seedance_native_audio": False},
            "subtitles": "skip",
            "summary": "画面无声 · TTS 配音 · 不烧字幕",
        },
    ]


def _duration_sec(
    settings: Settings,
    blueprint: WorkflowBlueprint | None,
    prompt: dict[str, Any] | None = None,
) -> int:
    if blueprint:
        return int(blueprint.video_spec.duration_sec or 15)
    if prompt:
        d = int(prompt.get("duration_sec") or prompt.get("segment_duration_sec") or 0)
        if d > 0:
            return d
    return int(settings.video_default_duration_sec or 15)


def is_single_segment(
    settings: Settings,
    blueprint: WorkflowBlueprint | None,
    prompt: dict[str, Any] | None = None,
) -> bool:
    if blueprint:
        return (blueprint.video_spec.segment_strategy or "single").strip().lower() == "single"
    if prompt:
        dur = _duration_sec(settings, blueprint, prompt)
        if dur <= 15:
            return True
    return (settings.video_segment_strategy or "single").strip().lower() == "single"


def _production_from_blueprint(blueprint: WorkflowBlueprint | None) -> Any | None:
    return blueprint.production if blueprint else None


def use_native_seedance(
    settings: Settings | None = None,
    *,
    blueprint: WorkflowBlueprint | None = None,
    prompt: dict[str, Any] | None = None,
) -> bool:
    """Seedance native audio in-video; skip Edge TTS + subtitle burn when True."""
    settings = settings or get_settings()
    prod = _production_from_blueprint(blueprint)

    if prod and prod.seedance_native_audio is not None:
        return bool(prod.seedance_native_audio)

    if prod:
        subs = (prod.subtitles or "").strip().lower()
        if prod.tts and subs == "burn_in":
            return False
        if subs == "skip" and not prod.tts:
            return True

    if not is_single_segment(settings, blueprint, prompt):
        return False
    if _duration_sec(settings, blueprint, prompt) > 15:
        return False
    if settings.tts_post_enabled:
        return False
    return True


# Back-compat alias
use_native_seedance_15s = use_native_seedance


def seedance_visual_only(
    settings: Settings | None = None,
    *,
    blueprint: WorkflowBlueprint | None = None,
    prompt: dict[str, Any] | None = None,
) -> bool:
    """True = mute Seedance audio (legacy TTS post path)."""
    if use_native_seedance(settings, blueprint=blueprint, prompt=prompt):
        return False
    settings = settings or get_settings()
    return bool(settings.tts_post_enabled and settings.tts_mute_seedance_audio)


def use_ugc_viral_prompt_format(
    settings: Settings | None = None,
    *,
    blueprint: WorkflowBlueprint | None = None,
    prompt: dict[str, Any] | None = None,
) -> bool:
    """Viral [0-3s][3-10s][10-15s] prompt blocks — from Blueprint, not product name."""
    settings = settings or get_settings()
    prod = _production_from_blueprint(blueprint)
    creative = blueprint.creative if blueprint else None

    if prod and prod.ugc_viral_format is not None:
        return bool(prod.ugc_viral_format)

    if creative and (creative.storyboard_profile or "").strip() == "ugc_viral_15s":
        return True

    if prod and (prod.prompt_format or "").strip() == "viral_15s_blocks":
        return use_native_seedance(settings, blueprint=blueprint, prompt=prompt)

    if creative and (creative.beat_structure or "").strip():
        return use_native_seedance(settings, blueprint=blueprint, prompt=prompt)

    return False


def production_mode_summary(
    settings: Settings | None = None,
    *,
    blueprint: WorkflowBlueprint | None = None,
) -> str:
    settings = settings or get_settings()
    native = use_native_seedance(settings, blueprint=blueprint)
    viral = use_ugc_viral_prompt_format(settings, blueprint=blueprint)
    if native and viral:
        subs = subtitle_mode_label(
            (blueprint.production.subtitles if blueprint and blueprint.production else None),
            native_audio=True,
        )
        return (
            f"Seedance 原生口播+画面 · 无后期 TTS · {subs} · "
            "viral 三段式 prompt [0-3s][3-10s][10-15s]"
        )
    if native:
        subs = subtitle_mode_label(
            (blueprint.production.subtitles if blueprint and blueprint.production else None),
            native_audio=True,
        )
        return f"Seedance 原生口播+画面 · 无后期 TTS · {subs}"
    if settings.tts_post_enabled:
        return "后期 Edge TTS 配音 + 字幕烧录（无声 Seedance 画面）"
    prod = _production_from_blueprint(blueprint)
    if prod and (prod.subtitles or "").strip().lower() == "skip":
        return "Seedance 原生配音 · 字幕跳过（后期自行处理）"
    return "Seedance 原生配音；字幕按 Blueprint production 配置"
