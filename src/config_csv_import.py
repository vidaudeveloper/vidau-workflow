"""固定配置 CSV 导入（按类型分开，与 JSON 全量包互补）。"""

from __future__ import annotations

import csv
import io
import uuid
from typing import Any

from src.config_sync import _ACCOUNT_EXPORT_KEYS, _DIRECTION_EXPORT_KEYS, _PRODUCT_EXPORT_KEYS, _pick
from src.db.repository import Repository

# 表头别名（不区分大小写，去空格）
_ACCOUNT_ALIASES: dict[str, tuple[str, ...]] = {
    "no": ("no", "no.", "序号"),
    "display_name": ("id", "账号名称", "账号名", "display_name"),
    "username": ("username", "账号", "handle"),
    "language": ("语言", "language", "lang"),
    "blogger_type": ("博主类型", "blogger_type"),
    "positioning": ("账号定位", "定位", "positioning"),
    "content_directions": ("账号内容方向", "内容方向", "content_directions"),
    "page_packaging": ("主页包装", "page_packaging"),
    "main_products": ("主推产品", "main_products"),
    "persona_style": ("账号人设风格", "人设风格", "persona_style"),
    "avatar_desc": ("头像图片", "头像", "avatar_desc", "头像（ai生成）"),
    "bio": ("bio/账号简介", "bio", "账号简介", "简介"),
}

_DIRECTION_ALIASES: dict[str, tuple[str, ...]] = {
    "name": ("name", "方向", "名称", "内容方向"),
    "description": ("description", "说明", "描述"),
    "short_code": ("short_code", "短码", "code"),
}

_PRODUCT_ALIASES: dict[str, tuple[str, ...]] = {
    "name": ("name", "产品", "产品名称", "名称"),
    "daily_price": ("daily_price", "日常价", "原价"),
    "promo_price": ("promo_price", "活动价", "促销价"),
    "purchase_link": ("purchase_link", "购买链接", "链接"),
    "listing_status": ("listing_status", "上架状态"),
    "conversion_method": ("conversion_method", "转化方式"),
    "selling_points": ("selling_points", "卖点"),
    "product_specs": ("product_specs", "外观说明", "产品外观与交互说明"),
}


def _norm_header(h: str) -> str:
    return (h or "").strip().lower().replace(" ", "")


def _map_row(row: dict[str, str], aliases: dict[str, tuple[str, ...]]) -> dict[str, str]:
    index: dict[str, str] = {}
    for raw_key, val in row.items():
        if raw_key is None:
            continue
        index[_norm_header(raw_key)] = (val or "").strip()

    out: dict[str, str] = {}
    for field, names in aliases.items():
        for name in names:
            key = _norm_header(name)
            if key in index and index[key]:
                out[field] = index[key]
                break
    return out


def _parse_csv_text(text: str) -> list[dict[str, str]]:
    if text.startswith("\ufeff"):
        text = text.lstrip("\ufeff")
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().has_header(sample)
    except csv.Error:
        dialect = True
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise ValueError("CSV 缺少表头行")
    rows: list[dict[str, str]] = []
    for row in reader:
        if not any((v or "").strip() for v in row.values()):
            continue
        rows.append({k: (v or "") for k, v in row.items() if k})
    if not rows:
        raise ValueError("CSV 无有效数据行")
    return rows


def _normalize_username(username: str) -> str:
    u = (username or "").strip()
    if u and not u.startswith("@"):
        u = f"@{u}"
    return u


def import_accounts_csv(text: str, *, repo: Repository | None = None) -> dict[str, int]:
    repo = repo or Repository()
    stats = {"created": 0, "updated": 0, "skipped": 0}
    for row in _parse_csv_text(text):
        mapped = _map_row(row, _ACCOUNT_ALIASES)
        display_name = (mapped.get("display_name") or "").strip()
        if not display_name:
            stats["skipped"] += 1
            continue
        try:
            no = int(float(mapped.get("no") or 0))
        except ValueError:
            no = 0
        fields = {
            "no": no,
            "display_name": display_name,
            "username": _normalize_username(mapped.get("username", "")),
            "language": mapped.get("language") or "英语",
            "blogger_type": mapped.get("blogger_type", ""),
            "positioning": mapped.get("positioning", ""),
            "content_directions": mapped.get("content_directions", ""),
            "page_packaging": mapped.get("page_packaging", ""),
            "main_products": mapped.get("main_products", ""),
            "persona_style": mapped.get("persona_style", ""),
            "avatar_desc": mapped.get("avatar_desc", ""),
            "bio": mapped.get("bio", ""),
        }
        existing = repo.get_account_by_no(no) if no else None
        if not existing:
            existing = next(
                (a for a in repo.list_accounts() if a.get("display_name") == display_name),
                None,
            )
        if existing:
            repo.update_account(existing["id"], fields)
            stats["updated"] += 1
        else:
            repo.create_account({"id": str(uuid.uuid4())[:8], **fields})
            stats["created"] += 1
    return stats


def import_directions_csv(text: str, *, repo: Repository | None = None) -> dict[str, int]:
    repo = repo or Repository()
    stats = {"created": 0, "updated": 0, "skipped": 0}
    for row in _parse_csv_text(text):
        mapped = _map_row(row, _DIRECTION_ALIASES)
        name = (mapped.get("name") or "").strip()
        if not name:
            stats["skipped"] += 1
            continue
        fields = _pick(
            {
                "name": name,
                "description": mapped.get("description", ""),
                "short_code": mapped.get("short_code", ""),
            },
            _DIRECTION_EXPORT_KEYS,
        )
        existing = next((d for d in repo.list_directions() if d.get("name") == name), None)
        if existing:
            repo.update_direction(existing["id"], {k: v for k, v in fields.items() if k != "name"})
            stats["updated"] += 1
        else:
            repo.create_direction({"id": str(uuid.uuid4())[:8], **fields})
            stats["created"] += 1
    return stats


def import_products_csv(text: str, *, repo: Repository | None = None) -> dict[str, int]:
    """产品 CSV 不含图片，仅更新文字/价格字段；新产品需后续在 UI 上传图片。"""
    repo = repo or Repository()
    stats = {"created": 0, "updated": 0, "skipped": 0}
    for row in _parse_csv_text(text):
        mapped = _map_row(row, _PRODUCT_ALIASES)
        name = (mapped.get("name") or "").strip()
        if not name:
            stats["skipped"] += 1
            continue
        fields = _pick(
            {
                "name": name,
                "daily_price": mapped.get("daily_price", ""),
                "promo_price": mapped.get("promo_price", ""),
                "purchase_link": mapped.get("purchase_link", ""),
                "listing_status": mapped.get("listing_status", ""),
                "conversion_method": mapped.get("conversion_method", ""),
                "selling_points": mapped.get("selling_points", ""),
                "product_specs": mapped.get("product_specs", ""),
            },
            _PRODUCT_EXPORT_KEYS,
        )
        existing = repo.get_product_by_name(name)
        if existing:
            repo.update_product(existing["id"], {k: v for k, v in fields.items() if k != "name"})
            stats["updated"] += 1
        else:
            repo.create_product({"id": str(uuid.uuid4())[:8], **fields})
            stats["created"] += 1
    return stats
