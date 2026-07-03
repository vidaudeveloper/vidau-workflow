"""多参考片 + 产品实拍图 → UGC 风格画像（达人穿搭、粉末真相、CTA）。"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from src.config import Settings, load_prompt
from src.pipeline.intake_extract import normalize_gemini_parts, prepare_attachment
from src.pipeline.intake_formats import MAX_INTAKE_FILES, MAX_INTAKE_TOTAL_BYTES
from src.pipeline.llm import LLMService
from src.pipeline.reference_decompose import _normalize_decomposition


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _list_norm(raw: dict[str, Any], key: str) -> None:
    val = raw.get(key)
    if val is None:
        raw[key] = []
    elif isinstance(val, str):
        raw[key] = [line.strip() for line in val.splitlines() if line.strip()]


def _normalize_style_learn(raw: dict[str, Any]) -> dict[str, Any]:
    out = _normalize_decomposition(raw)
    for key in (
        "creator_persona",
        "product_visual_truth",
        "cta_pattern",
        "lifestyle_notes",
    ):
        if key not in out:
            out[key] = "" if key in ("cta_pattern", "lifestyle_notes") else {}
    if isinstance(out.get("creator_persona"), str):
        out["creator_persona"] = {"memory_hook": out["creator_persona"]}
    if isinstance(out.get("product_visual_truth"), str):
        out["product_visual_truth"] = {"packaging": out["product_visual_truth"]}
    pv = out.get("product_visual_truth") or {}
    if isinstance(pv, dict):
        _list_norm(pv, "hero_shots")
        _list_norm(pv, "do_not_copy_from_video")
    return out


class ReferenceStyleLearnService:
    def __init__(self, settings: Settings):
        self.settings = settings

    async def learn(
        self,
        *,
        reference_videos: list[tuple[str, bytes]],
        product_images: list[tuple[str, bytes]] | None = None,
        user_note: str = "",
        product_hint: str = "",
    ) -> dict[str, Any]:
        if not reference_videos:
            raise ValueError("请至少提供 1 条参考视频")
        if len(reference_videos) > MAX_INTAKE_FILES:
            raise ValueError(f"参考视频最多 {MAX_INTAKE_FILES} 条")
        total = sum(len(b) for _, b in reference_videos)
        if product_images:
            total += sum(len(b) for _, b in product_images)
        if total > MAX_INTAKE_TOTAL_BYTES:
            raise ValueError(
                f"素材总大小不能超过 {MAX_INTAKE_TOTAL_BYTES // (1024 * 1024)}MB"
            )

        intro = [
            "请综合以下对标视频与产品实拍图，提炼 TikTok UGC 爆款风格画像（JSON）。",
            f"用户说明: {user_note.strip() or '无'}",
            f"产品: {product_hint.strip() or '无'}",
            f"参考视频数量: {len(reference_videos)}",
            f"产品实拍图数量: {len(product_images or [])}",
        ]
        user_parts: list[dict[str, Any]] = [{"text": "\n".join(intro)}]

        for i, (filename, data) in enumerate(reference_videos, 1):
            fmt, parts = prepare_attachment(data, filename)
            if fmt.category != "reference_video":
                raise ValueError(f"不支持的参考视频: {filename}")
            user_parts.append({"text": f"--- 参考视频 {i}: {filename} ---"})
            user_parts.extend(parts)

        for i, (filename, data) in enumerate(product_images or [], 1):
            fmt, parts = prepare_attachment(data, filename)
            if fmt.category != "product_image":
                raise ValueError(f"产品图格式不支持: {filename}")
            user_parts.append({"text": f"--- 产品实拍图 {i}: {filename}（外观/粉末以图为准）---"})
            user_parts.extend(parts)

        system = load_prompt("reference_style_learn_system")
        raw = await LLMService(self.settings).analyze_intake_materials(
            system=system,
            user_parts=normalize_gemini_parts(user_parts),
        )
        payload = _normalize_style_learn(raw if isinstance(raw, dict) else {})
        decomp_id = f"style_{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:6]}"
        return {
            "id": decomp_id,
            "source_filenames": [n for n, _ in reference_videos],
            "product_image_count": len(product_images or []),
            "payload": payload,
            "created_at": _now(),
        }


async def learn_reference_style(
    settings: Settings,
    **kwargs: Any,
) -> dict[str, Any]:
    return await ReferenceStyleLearnService(settings).learn(**kwargs)
