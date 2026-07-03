"""从商品名 / product_specs 解析套装模块白名单，约束首帧与分镜不得凭空增加同品牌产品。"""

from __future__ import annotations

import re
from typing import Any

from src.pipeline.brand_profile import BrandProfile


def _normalize_module_label(raw: str) -> str:
    s = (raw or "").strip()
    if not s:
        return ""
    # Apex300 → Apex 300
    s = re.sub(r"\bApex\s*(\d+)\b", r"Apex \1", s, flags=re.I)
    s = re.sub(r"\bElite\s*(\d+)\b", r"Elite \1", s, flags=re.I)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _split_kit_name(product_name: str) -> list[str]:
    name = (product_name or "").strip()
    if not name or "+" not in name:
        return []
    parts = [_normalize_module_label(p) for p in name.split("+")]
    return [p for p in parts if p]


def _parse_specs_kit_line(specs: str) -> list[str]:
    """匹配 product_specs 中「套装型号」行，如 Apex 300 + Charger 2 + DC Hub D1。"""
    text = specs or ""
    m = re.search(r"【套装型号】\s*([^\n【]+)", text)
    if not m:
        return []
    line = m.group(1)
    line = re.sub(r"三件套|两件套|四件套|套装|组合", "", line, flags=re.I)
    parts = re.split(r"\s*\+\s*", line)
    return [_normalize_module_label(p) for p in parts if _normalize_module_label(p)]


def _parse_specs_allowed_accessories(specs: str) -> list[str]:
    m = re.search(
        r"allowed_accessories\s*:\s*\[([^\]]+)\]",
        specs or "",
        flags=re.I,
    )
    if not m:
        return []
    inner = m.group(1)
    items = re.findall(r'"([^"]+)"', inner) or re.findall(r"'([^']+)'", inner)
    return [_normalize_module_label(x) for x in items if x.strip()]


def _parse_specs_hero(specs: str) -> str:
    m = re.search(r"hero_product\s*:\s*([^\n,]+)", specs or "", flags=re.I)
    if m:
        return _normalize_module_label(m.group(1).strip())
    m = re.search(r"（Hero）|（Hero unit）", specs or "", flags=re.I)
    if m:
        before = specs[: m.start()]
        hm = re.search(r"[-–]\s*([A-Za-z][^\n：:（(]{2,40}?)\s*（Hero", before)
        if hm:
            return _normalize_module_label(hm.group(1))
    return ""


def build_kit_constraint(
    product_name: str = "",
    product_specs: str = "",
    *,
    brand: BrandProfile | None = None,
) -> dict[str, Any] | None:
    """返回套装约束；非套装（单件）返回 None。"""
    modules = _parse_specs_kit_line(product_specs)
    if len(modules) < 2:
        modules = _split_kit_name(product_name)
    if len(modules) < 2:
        return None

    hero = _parse_specs_hero(product_specs) or modules[0]
    accessories = _parse_specs_allowed_accessories(product_specs)
    if not accessories:
        accessories = [m for m in modules if m.lower() != hero.lower()]
    # 去重保序
    seen: set[str] = set()
    allowed_modules: list[str] = []
    for m in [hero, *accessories]:
        key = m.lower()
        if key not in seen:
            seen.add(key)
            allowed_modules.append(m)

    module_count = len(allowed_modules)
    accessory_names = ", ".join(allowed_modules[1:]) if len(allowed_modules) > 1 else ""
    modules_list = ", ".join(allowed_modules)

    bw = f"{(brand or BrandProfile()).display} " if (brand and brand.has_brand) else ""

    constraint_text = (
        f"KIT WHITELIST — show EXACTLY {module_count} {bw}product module(s) in every frame: "
        f"{modules_list}. "
        f"Hero unit: {hero}."
        + (f" Accessories (only these): {accessory_names}." if accessory_names else "")
        + f" Do NOT add any other {bw}power station, battery pack, solar panel, "
        "expansion battery, fridge, or accessory module not in this list. "
        "Scene props (table, tent, mugs) are OK but must be plain/unbranded — "
        f"never extra {bw}hardware."
    )

    negative_extra = (
        f"extra {bw}products, additional power station, second battery unit, "
        f"solar panel, expansion battery, portable fridge as product, "
        f"invented {bw}module, more than {module_count} {bw}units, "
        f"products not in kit ({modules_list})"
    )

    return {
        "module_count": module_count,
        "hero_product": hero,
        "allowed_modules": allowed_modules,
        "allowed_accessories": allowed_modules[1:],
        "constraint_text": constraint_text,
        "negative_extra": negative_extra,
    }


def merge_kit_into_product_understanding(
    pu: dict[str, Any] | None,
    kit: dict[str, Any] | None,
) -> dict[str, Any]:
    """把套装白名单写入/覆盖 product_understanding。"""
    out = dict(pu or {})
    if not kit:
        return out
    out["hero_product"] = kit["hero_product"]
    out["allowed_accessories"] = list(kit["allowed_accessories"])
    out["allowed_modules"] = list(kit["allowed_modules"])
    out["module_count"] = kit["module_count"]
    forbidden = list(out.get("forbidden_in_frame") or [])
    extra_forbidden = [
        "extra branded products not in kit",
        "additional power stations or battery modules",
        "solar panels or expansion batteries not in kit",
        "portable fridge shown as powered product demo",
    ]
    for item in extra_forbidden:
        if item not in forbidden:
            forbidden.append(item)
    out["forbidden_in_frame"] = forbidden
    return out


def append_kit_negative(negative_prompt: str, kit: dict[str, Any] | None) -> str:
    if not kit:
        return (negative_prompt or "").strip()
    extra = kit.get("negative_extra", "")
    base = (negative_prompt or "").strip()
    if extra.lower() in base.lower():
        return base
    return f"{base}, {extra}".strip(", ") if base else extra
