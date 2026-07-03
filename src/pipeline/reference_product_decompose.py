"""参考视频 → 仅产品动作/粉末/包装真相（不复刻人物剧情）。"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from src.config import Settings, load_prompt
from src.pipeline.intake_extract import normalize_gemini_parts, prepare_attachment
from src.pipeline.llm import LLMService


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ReferenceProductDecomposeService:
    def __init__(self, settings: Settings):
        self.settings = settings

    async def decompose(
        self,
        *,
        video_bytes: bytes,
        filename: str,
        product_hint: str = "",
        user_note: str = "",
    ) -> dict[str, Any]:
        if not video_bytes:
            raise ValueError("参考视频为空")
        fmt, parts = prepare_attachment(video_bytes, filename)
        intro = [
            "只分析产品本体：撕开方式、粉末、包装。不要分析人物剧情。",
            f"产品: {product_hint or 'PopSmilz Oral Probiotics'}",
            f"说明: {user_note or '无'}",
        ]
        user_parts: list[dict[str, Any]] = [{"text": "\n".join(intro)}]
        user_parts.extend(parts)
        system = load_prompt("reference_product_video_system")
        raw = await LLMService(self.settings).analyze_intake_materials(
            system=system,
            user_parts=normalize_gemini_parts(user_parts),
        )
        payload = raw if isinstance(raw, dict) else {}
        decomp_id = f"prodvid_{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:6]}"
        return {
            "id": decomp_id,
            "source_filename": filename,
            "payload": payload,
            "created_at": _now(),
        }


async def decompose_product_reference_video(
    settings: Settings,
    *,
    video_bytes: bytes,
    filename: str,
    product_hint: str = "",
    user_note: str = "",
) -> dict[str, Any]:
    svc = ReferenceProductDecomposeService(settings)
    return await svc.decompose(
        video_bytes=video_bytes,
        filename=filename,
        product_hint=product_hint,
        user_note=user_note,
    )
