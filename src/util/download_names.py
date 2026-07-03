"""成片 / 素材包下载文件名：产品名-方向-账号.后缀"""

from __future__ import annotations

import re

_INVALID_WIN = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def sanitize_filename_part(text: str) -> str:
    cleaned = _INVALID_WIN.sub("", (text or "").strip())
    return re.sub(r"\s+", " ", cleaned).strip(". ")


def build_delivery_basename(
    product: str,
    direction: str,
    account: str = "",
    *,
    fallback: str = "VidAU-Flow",
) -> str:
    """例：Elite 300-④极端天气应急型-No Gas Backup"""
    parts = [
        sanitize_filename_part(product),
        sanitize_filename_part(direction),
        sanitize_filename_part(account) or "通用",
    ]
    name = "-".join(p for p in parts if p)
    return name or fallback


def delivery_filename(
    product: str,
    direction: str,
    account: str = "",
    *,
    ext: str,
    fallback: str = "VidAU-Flow",
) -> str:
    ext = (ext or "").lstrip(".").lower() or "bin"
    return f"{build_delivery_basename(product, direction, account, fallback=fallback)}.{ext}"
