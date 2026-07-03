"""产品图视觉分析 — 复用 LLMService（与脚本生成相同的 Vertex / Gemini 路由）。"""

from __future__ import annotations

import base64
import mimetypes
from pathlib import Path
from typing import Any

from src.config import Settings, load_prompt
from src.pipeline.gemini_client import gemini_configured
from src.pipeline.llm import LLMService
from src.uploads import UPLOADS_DIR, resolve_image_url_for_api

MAX_VISION_IMAGES = 4


def _vision_text_field(value: Any) -> str:
    """Gemini 有时把卖点等字段返回为 list，入库前统一为字符串。"""
    if value is None:
        return ""
    if isinstance(value, list):
        return "\n".join(str(item).strip() for item in value if str(item).strip())
    if isinstance(value, dict):
        import json

        return json.dumps(value, ensure_ascii=False)
    return str(value).strip()


def _normalize_vision_result(result: dict[str, Any]) -> dict[str, Any]:
    specs = _vision_text_field(result.get("product_specs_text") or result.get("appearance_notes"))
    selling = _vision_text_field(result.get("selling_points_suggested"))
    result["product_specs_text"] = specs
    result["selling_points_suggested"] = selling
    notes = result.get("confidence_notes")
    if notes is not None and not isinstance(notes, str):
        result["confidence_notes"] = _vision_text_field(notes)
    return result


def _inline_part_from_url(image_url: str) -> dict[str, Any] | None:
    resolved = resolve_image_url_for_api(image_url)
    if not resolved.startswith("data:"):
        return None
    header, _, b64 = resolved.partition(",")
    mime = header.removeprefix("data:").split(";")[0] or "image/jpeg"
    return {"inline_data": {"mime_type": mime, "data": b64}}


def _inline_part_from_path(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    ext = path.suffix.lower()
    mime = mimetypes.guess_type(path.name)[0] or {
        ".heic": "image/heic",
        ".heif": "image/heif",
    }.get(ext, "image/jpeg")
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return {"inline_data": {"mime_type": mime, "data": data}}


def image_parts_from_urls(image_urls: list[str]) -> list[dict[str, Any]]:
    parts: list[dict[str, Any]] = []
    for url in image_urls[:MAX_VISION_IMAGES]:
        part = _inline_part_from_url(url)
        if part:
            parts.append(part)
            continue
        if url.startswith("/uploads/"):
            part = _inline_part_from_path(UPLOADS_DIR / url.removeprefix("/uploads/"))
            if part:
                parts.append(part)
    return parts


class ProductVisionService:
    def __init__(self, settings: Settings):
        self.settings = settings

    async def analyze(
        self,
        *,
        product_name: str,
        image_urls: list[str],
        existing_specs: str = "",
        existing_selling_points: str = "",
    ) -> dict[str, Any]:
        if not gemini_configured(self.settings) and not self.settings.nuwa_api_key:
            raise RuntimeError("未配置 Vertex/Gemini 凭据或 NUWA_API_KEY，无法进行产品图识别")

        image_parts = image_parts_from_urls(image_urls)
        if not image_parts:
            raise ValueError(
                "没有可用的产品图：请先上传至少 1 张图片；"
                "若已上传仍失败，请确认服务器 data/uploads/products/ 下存在对应文件"
            )

        system = load_prompt("product_vision_system")
        user_lines = [
            f"产品名称: {product_name or '未知'}",
            f"参考图数量: {len(image_parts)}",
        ]
        if existing_specs.strip():
            user_lines.append(f"已有外观说明（可修正/补充）:\n{existing_specs.strip()}")
        if existing_selling_points.strip():
            user_lines.append(f"已有卖点（可补充）:\n{existing_selling_points.strip()}")
        user_lines.append("请分析以上图片并输出 JSON。")
        user_text = "\n".join(user_lines)

        user_parts: list[dict[str, Any]] = [{"text": user_text}]
        for i, img in enumerate(image_parts, 1):
            user_parts.append({"text": f"--- 参考图 {i} ---"})
            user_parts.append(img)

        result = await LLMService(self.settings).analyze_product_vision(
            system=system,
            user_text=user_text,
            user_parts=user_parts,
            image_parts=image_parts,
        )
        result = _normalize_vision_result(result)
        result.setdefault("product_specs_text", result.get("appearance_notes", ""))
        return result


async def analyze_product_images(
    settings: Settings,
    *,
    product_name: str,
    image_urls: list[str],
    existing_specs: str = "",
    existing_selling_points: str = "",
) -> dict[str, Any]:
    return await ProductVisionService(settings).analyze(
        product_name=product_name,
        image_urls=image_urls,
        existing_specs=existing_specs,
        existing_selling_points=existing_selling_points,
    )
