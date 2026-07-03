"""批次语言与 LLM 系统提示词 — 由 Blueprint prompt_profile 驱动，不按产品名分支。"""

from __future__ import annotations

from typing import Any

from src.config import load_prompt
from src.pipeline.workflow_blueprint import WorkflowBlueprint

SPANISH_ALIASES = frozenset(
    {"西语", "西班牙语", "spanish", "es", "es-mx", "es-es", "español", "espanol"}
)

# prompt_profile / storyboard_profile → config/prompts/{name}.txt
SCRIPT_PROFILE_FILES: dict[str, str] = {
    "default": "script_system",
    "ugc_15s": "script_system_pop_smilz",
    "ugc_native": "script_system_pop_smilz",
}

STORYBOARD_PROFILE_FILES: dict[str, str] = {
    "default": "storyboard_system",
    "ugc_viral_15s": "storyboard_system_pop_smilz_ugc",
    "viral_15s_blocks": "storyboard_system_pop_smilz_ugc",
}


def is_spanish(language: str | None) -> bool:
    lang = (language or "").strip().lower()
    if not lang:
        return False
    if lang in SPANISH_ALIASES:
        return True
    return lang.startswith("es") or "西语" in lang or "西班牙" in lang


def language_label(language: str | None) -> str:
    return "西语" if is_spanish(language) else "英语"


def resolve_script_profile(
    *,
    blueprint: WorkflowBlueprint | None = None,
    payload: dict[str, Any] | None = None,
) -> str:
    p = payload or {}
    if p.get("script_prompt_profile"):
        return str(p["script_prompt_profile"]).strip()
    if blueprint and (blueprint.creative.prompt_profile or "").strip():
        return blueprint.creative.prompt_profile.strip()
    return "default"


def resolve_storyboard_profile(
    *,
    blueprint: WorkflowBlueprint | None = None,
    payload: dict[str, Any] | None = None,
) -> str:
    p = payload or {}
    if p.get("storyboard_prompt_profile"):
        return str(p["storyboard_prompt_profile"]).strip()
    if p.get("ugc_viral_15s_native"):
        return "ugc_viral_15s"
    if blueprint and (blueprint.creative.storyboard_profile or "").strip():
        return blueprint.creative.storyboard_profile.strip()
    prod = blueprint.production if blueprint else None
    if prod and (prod.prompt_format or "").strip() == "viral_15s_blocks":
        return "ugc_viral_15s"
    return "default"


def _load_profile_prompt(profile: str, registry: dict[str, str], language: str | None) -> str:
    key = (profile or "default").strip().lower()
    base = registry.get(key, registry["default"])
    if key == "default" and is_spanish(language):
        if registry is SCRIPT_PROFILE_FILES:
            base = "script_system_es"
        else:
            base = "storyboard_system_es"
    return load_prompt(base) + "\n\n" + load_prompt("reference_benchmark")


def script_system_prompt(
    language: str | None,
    *,
    product: str | None = None,
    blueprint: WorkflowBlueprint | None = None,
    payload: dict[str, Any] | None = None,
    prompt_profile: str = "",
) -> str:
    profile = prompt_profile or resolve_script_profile(blueprint=blueprint, payload=payload)
    return _load_profile_prompt(profile, SCRIPT_PROFILE_FILES, language)


def storyboard_system_prompt(
    language: str | None,
    *,
    product: str | None = None,
    blueprint: WorkflowBlueprint | None = None,
    payload: dict[str, Any] | None = None,
) -> str:
    profile = resolve_storyboard_profile(blueprint=blueprint, payload=payload)
    return _load_profile_prompt(profile, STORYBOARD_PROFILE_FILES, language)


def oral_language_instruction(language: str | None, brand: str = "") -> str:
    brand = (brand or "").strip()
    brand_note = f"品牌 {brand} 保持拼写" if brand else "品牌名保持正确拼写"
    if is_spanish(language):
        return (
            "【成片语言】西班牙语（拉美 TikTok 口语，es-MX）。"
            "所有口播字段 audio / hook / cta / spoken 必须用西班牙语；"
            f"{brand_note}；技术单位可用西语或通用缩写。"
        )
    return "【成片语言】英语（美式口语）。所有口播字段必须为英文。"
