"""变体方向库 — 路径与内容均由 Workflow Blueprint 指定。"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from src.config import ROOT
from src.pipeline.workflow_blueprint import WorkflowBlueprint

DEFAULT_LIBRARY = "config/creative/pop_smilz_15_directions.json"


@lru_cache(maxsize=16)
def _load_library_cached(resolved_path: str) -> tuple[dict[str, Any], ...]:
    path = Path(resolved_path)
    if not path.is_file():
        return ()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return tuple(x for x in data if isinstance(x, dict))
    except (json.JSONDecodeError, OSError):
        pass
    return ()


def resolve_library_path(library_path: str = "") -> Path | None:
    raw = (library_path or "").strip()
    if not raw:
        return None
    path = Path(raw)
    if not path.is_absolute():
        path = ROOT / raw
    return path if path.is_file() else None


def load_direction_library(library_path: str = "") -> list[dict[str, Any]]:
    path = resolve_library_path(library_path)
    if not path:
        return []
    return list(_load_library_cached(str(path.resolve())))


def direction_for_variant(
    variant_index: int,
    *,
    library_path: str = "",
    variant_scripts: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    scripts = variant_scripts or []
    if scripts:
        idx = max(1, variant_index) - 1
        return scripts[idx % len(scripts)]
    dirs = load_direction_library(library_path)
    if not dirs:
        return None
    idx = max(1, variant_index) - 1
    return dirs[idx % len(dirs)]


def should_inject_variant_direction(blueprint: WorkflowBlueprint | None) -> bool:
    if not blueprint:
        return False
    if (blueprint.batch.direction_library or "").strip():
        return True
    return bool(blueprint.creative.variant_scripts)


def effective_direction_library(blueprint: WorkflowBlueprint | None) -> str:
    if not blueprint:
        return ""
    return (blueprint.batch.direction_library or "").strip()


def format_direction_block(
    variant_index: int,
    *,
    library_path: str = "",
    variant_scripts: list[dict[str, Any]] | None = None,
    product_visual_truth: dict[str, Any] | None = None,
) -> str:
    d = direction_for_variant(
        variant_index,
        library_path=library_path,
        variant_scripts=variant_scripts,
    )
    if not d:
        return ""

    pv = product_visual_truth or {}
    tear = pv.get("tear_method") or pv.get("product_action") or "按 product_visual_truth 执行产品交互"
    powder = pv.get("appearance_notes") or pv.get("powder_notes") or "按产品规格与参考图"
    forbidden = pv.get("forbidden_in_frame") or pv.get("do_not_copy_from_video") or []
    forbid_txt = "、".join(str(x) for x in forbidden[:6]) if forbidden else "可读字幕烧录、平台 Logo/水印"

    lines = [
        f"--- 本集创意变体 #{d.get('id', variant_index)}: {d.get('title', d.get('hook', ''))} ---",
    ]
    for label, key in (
        ("痛点", "pain_point"),
        ("场景", "scene"),
        ("穿搭", "wardrobe"),
        ("0-3s Hook", "hook"),
        ("核心段", "core"),
        ("CTA 口播", "cta_voice"),
    ):
        val = (d.get(key) or "").strip()
        if val:
            lines.append(f"{label}: {val}")
    if d.get("monologue"):
        lines.append(f"口播参考（自然改写勿照抄）: {d['monologue'].strip()}")
    lines.append(f"产品动作锁定: {tear} → {powder}")
    lines.append(f"画面禁止: {forbid_txt}")
    lines.append("禁止复刻参考视频人物/剧情/背景，仅学产品外观与脚本化交互。")
    return "\n".join(lines)
