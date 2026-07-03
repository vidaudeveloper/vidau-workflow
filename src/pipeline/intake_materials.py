"""Copilot 参考素材解析 — 多格式 → 结构化 brief。"""

from __future__ import annotations

from typing import Any

from src.config import Settings, load_prompt
from src.pipeline.gemini_client import gemini_configured
from src.pipeline.intake_extract import extract_product_page_url, normalize_gemini_parts, prepare_attachment
from src.pipeline.intake_formats import (
    MAX_INTAKE_FILES,
    MAX_INTAKE_TOTAL_BYTES,
    extract_video_url,
)
from src.pipeline.llm import LLMService


def _normalize_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, str) and value.strip():
        return [line.strip() for line in value.splitlines() if line.strip()]
    return []


def _normalize_result(raw: dict[str, Any]) -> dict[str, Any]:
    selling = _normalize_list(raw.get("selling_points"))
    hooks = _normalize_list(raw.get("hook_patterns"))
    specs = str(raw.get("product_specs_summary") or "").strip()
    style = str(raw.get("reference_style") or "").strip()
    brief = str(raw.get("suggested_brief") or "").strip()
    product = str(raw.get("product_name") or "").strip()
    direction = str(raw.get("suggested_direction") or "").strip()
    notes = str(raw.get("confidence_notes") or "").strip()

    lines = ["--- 参考素材分析 ---"]
    if product:
        lines.append(f"产品: {product}")
    if specs:
        lines.append(f"产品要点:\n{specs}")
    if selling:
        lines.append("卖点:\n" + "\n".join(f"- {s}" for s in selling))
    if style:
        lines.append(f"对标风格:\n{style}")
    if hooks:
        lines.append("钩子参考:\n" + "\n".join(f"- {h}" for h in hooks))
    if notes:
        lines.append(f"备注: {notes}")
    material_context = "\n".join(lines).strip()

    return {
        "product_name": product,
        "selling_points": selling,
        "product_specs_summary": specs,
        "reference_style": style,
        "hook_patterns": hooks,
        "suggested_brief": brief,
        "suggested_direction": direction,
        "confidence_notes": notes,
        "material_context": material_context,
    }


class IntakeMaterialsService:
    def __init__(self, settings: Settings):
        self.settings = settings

    async def analyze(
        self,
        *,
        attachments: list[tuple[str, bytes]],
        reference_video_url: str = "",
        product_page_url: str = "",
        user_note: str = "",
        product_hint: str = "",
    ) -> dict[str, Any]:
        if not gemini_configured(self.settings) and not self.settings.nuwa_api_key:
            raise RuntimeError("未配置 Vertex/Gemini 或 NUWA，无法解析参考素材")

        ref_url = (reference_video_url or "").strip() or extract_video_url(user_note)
        page_url = (product_page_url or "").strip() or extract_product_page_url(
            user_note, exclude=ref_url
        )

        if not attachments and not ref_url and not page_url and not user_note.strip():
            raise ValueError(
                "请上传参考素材（PDF/Word/表格/视频/产品图）或粘贴对标视频/产品页链接"
            )
        if len(attachments) > MAX_INTAKE_FILES:
            raise ValueError(f"单次最多上传 {MAX_INTAKE_FILES} 个文件")

        total_bytes = sum(len(data) for _, data in attachments)
        if total_bytes > MAX_INTAKE_TOTAL_BYTES:
            raise ValueError(
                f"素材总大小不能超过 {MAX_INTAKE_TOTAL_BYTES // (1024 * 1024)}MB"
            )

        user_parts: list[dict[str, Any]] = []
        sources: dict[str, Any] = {
            "files": [],
            "reference_video_url": ref_url,
            "product_page_url": page_url,
            "counts": {
                "product_doc": 0,
                "table": 0,
                "reference_video": 0,
                "product_image": 0,
                "text": 0,
            },
        }

        intro = [
            "请根据以下材料输出 JSON。",
            f"用户产品提示: {product_hint.strip() or '无'}",
            f"用户补充说明: {user_note.strip() or '无'}",
        ]
        if ref_url:
            intro.append(f"对标视频链接: {ref_url}")
        if page_url:
            intro.append(f"产品页链接: {page_url}")
        user_parts.append({"text": "\n".join(intro)})

        for filename, data in attachments:
            fmt, parts = prepare_attachment(data, filename)
            user_parts.extend(parts)
            sources["files"].append(
                {"name": filename, "category": fmt.category, "bytes": len(data)}
            )
            sources["counts"][fmt.category] = int(sources["counts"].get(fmt.category, 0)) + 1

        system = load_prompt("intake_materials_system")
        raw = await LLMService(self.settings).analyze_intake_materials(
            system=system,
            user_parts=normalize_gemini_parts(user_parts),
        )
        result = _normalize_result(raw)
        result["sources"] = sources
        if page_url and not result.get("suggested_brief"):
            result["suggested_brief"] = (
                f"参考产品页 {page_url}，{user_note.strip() or '制作竖屏 15s 产品广告'}"
            )
        if ref_url and not result.get("reference_style"):
            result["reference_style"] = f"对标参考视频: {ref_url}"
        return result


async def analyze_intake_materials(
    settings: Settings,
    **kwargs: Any,
) -> dict[str, Any]:
    return await IntakeMaterialsService(settings).analyze(**kwargs)
