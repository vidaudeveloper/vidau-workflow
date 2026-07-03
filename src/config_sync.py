"""固定配置（产品 / 账号人设 / 内容方向）导出与导入。"""

from __future__ import annotations

import base64
import json
import mimetypes
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.db.repository import Repository
from src.uploads import (
    PRODUCT_IMAGES_DIR,
    UPLOADS_DIR,
    ensure_upload_dirs,
    parse_product_image_urls,
    product_image_db_fields,
)

BUNDLE_VERSION = 1

_PRODUCT_EXPORT_KEYS = (
    "name",
    "daily_price",
    "promo_price",
    "purchase_link",
    "listing_status",
    "conversion_method",
    "product_specs",
    "selling_points",
    "product_specs_draft",
    "selling_points_draft",
    "product_specs_confirmed",
    "vision_analyzed_at",
)

_ACCOUNT_EXPORT_KEYS = (
    "no",
    "display_name",
    "username",
    "language",
    "blogger_type",
    "positioning",
    "content_directions",
    "page_packaging",
    "main_products",
    "persona_style",
    "avatar_desc",
    "bio",
    "conversion_method",
)

_DIRECTION_EXPORT_KEYS = ("name", "description", "short_code")


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _pick(row: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    return {k: row.get(k, "") for k in keys}


def _read_local_image(url: str) -> dict[str, str] | None:
    if not url or url.startswith(("http://", "https://", "data:")):
        return None
    rel = url.removeprefix("/uploads/")
    path = UPLOADS_DIR / rel
    if not path.is_file():
        return None
    ext = path.suffix.lower() or ".jpg"
    mime = mimetypes.guess_type(path.name)[0] or "image/jpeg"
    return {
        "filename": path.name,
        "content_base64": base64.b64encode(path.read_bytes()).decode("ascii"),
        "mime": mime,
        "ext": ext,
    }


def _save_image_blob(blob: dict[str, str]) -> str:
    ensure_upload_dirs()
    raw = blob.get("content_base64", "")
    if not raw:
        return ""
    ext = blob.get("ext") or Path(blob.get("filename", "")).suffix.lower() or ".jpg"
    data = base64.b64decode(raw)
    filename = f"{uuid.uuid4().hex}{ext}"
    path = PRODUCT_IMAGES_DIR / filename
    path.write_bytes(data)
    return f"/uploads/products/{filename}"


def export_fixed_config(repo: Repository | None = None) -> dict[str, Any]:
    repo = repo or Repository()
    products_out: list[dict[str, Any]] = []
    for p in repo.list_products():
        item = _pick(p, _PRODUCT_EXPORT_KEYS)
        item["product_specs_confirmed"] = bool(int(p.get("product_specs_confirmed") or 0))
        images: list[dict[str, str]] = []
        for url in parse_product_image_urls(p):
            blob = _read_local_image(url)
            if blob:
                images.append(blob)
        item["images"] = images
        products_out.append(item)

    accounts_out = [_pick(a, _ACCOUNT_EXPORT_KEYS) for a in repo.list_accounts()]
    directions_out = [_pick(d, _DIRECTION_EXPORT_KEYS) for d in repo.list_directions()]

    return {
        "version": BUNDLE_VERSION,
        "kind": "fixed_config",
        "exported_at": _now(),
        "products": products_out,
        "accounts": accounts_out,
        "directions": directions_out,
    }


def import_fixed_config(
    bundle: dict[str, Any],
    *,
    repo: Repository | None = None,
) -> dict[str, int]:
    if bundle.get("kind") != "fixed_config":
        raise ValueError("不是固定配置包（kind 须为 fixed_config）")
    version = int(bundle.get("version") or 0)
    if version != BUNDLE_VERSION:
        raise ValueError(f"不支持的配置包版本：{version}")

    repo = repo or Repository()
    stats = {"products_created": 0, "products_updated": 0, "accounts_created": 0, "accounts_updated": 0, "directions_created": 0, "directions_updated": 0}

    for raw in bundle.get("directions") or []:
        name = (raw.get("name") or "").strip()
        if not name:
            continue
        fields = _pick(raw, _DIRECTION_EXPORT_KEYS)
        existing = next((d for d in repo.list_directions() if d.get("name") == name), None)
        if existing:
            repo.update_direction(existing["id"], {k: v for k, v in fields.items() if k != "name"})
            stats["directions_updated"] += 1
        else:
            repo.create_direction({"id": str(uuid.uuid4())[:8], **fields})
            stats["directions_created"] += 1

    for raw in bundle.get("accounts") or []:
        display_name = (raw.get("display_name") or "").strip()
        if not display_name:
            continue
        fields = _pick(raw, _ACCOUNT_EXPORT_KEYS)
        no = int(fields.get("no") or 0)
        existing = repo.get_account_by_no(no) if no else None
        if not existing:
            existing = next((a for a in repo.list_accounts() if a.get("display_name") == display_name), None)
        if existing:
            repo.update_account(existing["id"], fields)
            stats["accounts_updated"] += 1
        else:
            repo.create_account({"id": str(uuid.uuid4())[:8], **fields})
            stats["accounts_created"] += 1

    for raw in bundle.get("products") or []:
        name = (raw.get("name") or "").strip()
        if not name:
            continue
        fields = _pick(raw, _PRODUCT_EXPORT_KEYS)
        fields["product_specs_confirmed"] = 1 if raw.get("product_specs_confirmed") else 0
        urls: list[str] = []
        for blob in raw.get("images") or []:
            if isinstance(blob, dict) and blob.get("content_base64"):
                url = _save_image_blob(blob)
                if url:
                    urls.append(url)
        if urls:
            fields.update(product_image_db_fields(urls))

        existing = repo.get_product_by_name(name)
        extra = {
            k: fields[k]
            for k in (
                "product_specs_draft",
                "selling_points_draft",
                "product_specs_confirmed",
                "vision_analyzed_at",
                "image_url",
                "image_urls_json",
            )
            if k in fields
        }
        if existing:
            update_fields = {k: v for k, v in fields.items() if k not in ("name", *extra)}
            update_fields.update(extra)
            repo.update_product(existing["id"], update_fields)
            stats["products_updated"] += 1
        else:
            pid = str(uuid.uuid4())[:8]
            create_fields = {k: v for k, v in fields.items() if k not in extra}
            repo.create_product({"id": pid, **create_fields})
            if extra:
                repo.update_product(pid, extra)
            stats["products_created"] += 1

    return stats


def export_fixed_config_json(repo: Repository | None = None, *, indent: int = 2) -> str:
    return json.dumps(export_fixed_config(repo), ensure_ascii=False, indent=indent)


def import_fixed_config_json(text: str, *, repo: Repository | None = None) -> dict[str, int]:
    bundle = json.loads(text)
    if not isinstance(bundle, dict):
        raise ValueError("配置包须为 JSON 对象")
    return import_fixed_config(bundle, repo=repo)
