"""Copilot 参考素材 — 支持格式清单（前后端对齐）。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

# 单文件 / 单次请求上限
MAX_INTAKE_FILES = 8
MAX_INTAKE_TOTAL_BYTES = 100 * 1024 * 1024
MAX_TEXT_EXCERPT_CHARS = 48_000

VIDEO_URL_RE = re.compile(
    r"https?://(?:www\.)?(?:"
    r"tiktok\.com|vm\.tiktok\.com|"
    r"youtube\.com|youtu\.be|"
    r"instagram\.com|"
    r"douyin\.com|v\.douyin\.com|"
    r"bilibili\.com|"
    r"facebook\.com|fb\.watch"
    r")[^\s\])\"']+",
    re.I,
)


@dataclass(frozen=True)
class IntakeFormat:
    category: str
    extensions: tuple[str, ...]
    mime_types: tuple[str, ...]
    max_bytes: int
    label_zh: str
    label_en: str


# 对话框可选上传：产品说明、表格、对标视频、产品图、文本 brief
INTAKE_FORMATS: tuple[IntakeFormat, ...] = (
    IntakeFormat(
        category="product_doc",
        extensions=(".pdf",),
        mime_types=("application/pdf",),
        max_bytes=20 * 1024 * 1024,
        label_zh="产品介绍 PDF",
        label_en="Product PDF",
    ),
    IntakeFormat(
        category="product_doc",
        extensions=(".docx",),
        mime_types=(
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ),
        max_bytes=15 * 1024 * 1024,
        label_zh="Word 产品介绍",
        label_en="Word DOCX",
    ),
    IntakeFormat(
        category="table",
        extensions=(".csv",),
        mime_types=("text/csv", "application/csv", "text/plain"),
        max_bytes=5 * 1024 * 1024,
        label_zh="CSV 表格",
        label_en="CSV table",
    ),
    IntakeFormat(
        category="table",
        extensions=(".xlsx",),
        mime_types=(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ),
        max_bytes=10 * 1024 * 1024,
        label_zh="Excel 表格",
        label_en="Excel XLSX",
    ),
    IntakeFormat(
        category="reference_video",
        extensions=(".mp4", ".webm", ".mov", ".m4v"),
        mime_types=("video/mp4", "video/webm", "video/quicktime", "video/x-m4v"),
        max_bytes=80 * 1024 * 1024,
        label_zh="对标参考视频",
        label_en="Reference video",
    ),
    IntakeFormat(
        category="product_image",
        extensions=(".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif"),
        mime_types=(
            "image/jpeg",
            "image/png",
            "image/webp",
            "image/heic",
            "image/heif",
        ),
        max_bytes=30 * 1024 * 1024,
        label_zh="产品参考图",
        label_en="Product image",
    ),
    IntakeFormat(
        category="text",
        extensions=(".txt", ".md"),
        mime_types=("text/plain", "text/markdown"),
        max_bytes=2 * 1024 * 1024,
        label_zh="文本 Brief",
        label_en="Text brief",
    ),
)

_EXTENSION_TO_FORMAT: dict[str, IntakeFormat] = {}
for _fmt in INTAKE_FORMATS:
    for _ext in _fmt.extensions:
        _EXTENSION_TO_FORMAT[_ext] = _fmt


def extract_video_url(text: str) -> str:
    m = VIDEO_URL_RE.search(text or "")
    return (m.group(0) if m else "").rstrip(".,;)")


def classify_intake_filename(filename: str) -> IntakeFormat | None:
    ext = ("." + filename.rsplit(".", 1)[-1].lower()) if "." in filename else ""
    if ext in _EXTENSION_TO_FORMAT:
        return _EXTENSION_TO_FORMAT[ext]
    return None


def intake_formats_public() -> dict[str, Any]:
    """供 /api/toc/intake/formats 与前端 accept 使用。"""
    categories: dict[str, dict[str, Any]] = {}
    for fmt in INTAKE_FORMATS:
        bucket = categories.setdefault(
            fmt.category,
            {
                "category": fmt.category,
                "extensions": [],
                "mime_types": [],
                "labels": {"zh": fmt.label_zh, "en": fmt.label_en},
            },
        )
        bucket["extensions"] = sorted(
            set(bucket["extensions"]) | set(fmt.extensions)
        )
        bucket["mime_types"] = sorted(
            set(bucket["mime_types"]) | set(fmt.mime_types)
        )
    all_ext = sorted({e for f in INTAKE_FORMATS for e in f.extensions})
    return {
        "max_files": MAX_INTAKE_FILES,
        "max_total_bytes": MAX_INTAKE_TOTAL_BYTES,
        "accept": ",".join(all_ext),
        "categories": list(categories.values()),
        "supported_summary": {
            "zh": "可选上传：PDF/Word、CSV/Excel、对标视频、产品图、TXT/MD；也可只打字或贴链接",
            "en": "Optional uploads: PDF/Word, CSV/Excel, reference video, images, TXT/MD — or type/paste links only",
        },
    }
