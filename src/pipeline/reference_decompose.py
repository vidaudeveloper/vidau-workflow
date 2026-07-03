"""参考视频结构化拆解 — 驱动 Workflow Blueprint。"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from src.config import Settings, load_prompt
from src.pipeline.intake_extract import normalize_gemini_parts, prepare_attachment
from src.pipeline.llm import LLMService


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_decomposition(raw: dict[str, Any]) -> dict[str, Any]:
    out = dict(raw)
    for key in (
        "duration_sec",
        "recommended_duration_sec",
        "shot_count_estimate",
        "recommended_segment_duration_sec",
        "hook_window_sec",
        "product_reveal_timing_sec",
    ):
        if key in out and out[key] is not None:
            try:
                out[key] = int(out[key])
            except (TypeError, ValueError):
                pass
    for key in ("structure_beats", "scene_types", "reusable_for_clone", "not_recommended_to_clone"):
        val = out.get(key)
        if val is None:
            out[key] = []
        elif isinstance(val, str):
            out[key] = [line.strip() for line in val.splitlines() if line.strip()]
    return out


class ReferenceDecomposeService:
    def __init__(self, settings: Settings):
        self.settings = settings

    async def decompose(
        self,
        *,
        video_bytes: bytes,
        filename: str,
        user_note: str = "",
        product_hint: str = "",
    ) -> dict[str, Any]:
        if not video_bytes:
            raise ValueError("参考视频文件为空")
        fmt, parts = prepare_attachment(video_bytes, filename)
        if fmt.category != "reference_video":
            raise ValueError(f"不支持的参考视频格式: {filename}")

        intro = [
            "请拆解以下对标/参考视频的结构，输出 JSON。",
            f"用户说明: {user_note.strip() or '无'}",
            f"产品提示: {product_hint.strip() or '无'}",
        ]
        user_parts = [{"text": "\n".join(intro)}]
        user_parts.extend(parts)

        system = load_prompt("reference_decompose_system")
        raw = await LLMService(self.settings).analyze_intake_materials(
            system=system,
            user_parts=normalize_gemini_parts(user_parts),
        )
        decomposition = _normalize_decomposition(raw if isinstance(raw, dict) else {})
        decomp_id = f"ref_{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:6]}"
        return {
            "id": decomp_id,
            "source_filename": filename,
            "payload": decomposition,
            "created_at": _now(),
        }


async def decompose_reference_video(
    settings: Settings,
    **kwargs: Any,
) -> dict[str, Any]:
    return await ReferenceDecomposeService(settings).decompose(**kwargs)
