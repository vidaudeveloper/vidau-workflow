#!/usr/bin/env python3
"""运维诊断：产品图视觉识别（LLMService / Vertex）是否可用。"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config import get_settings  # noqa: E402
from src.pipeline.gemini_client import gemini_configured, gemini_use_vertex  # noqa: E402
from src.pipeline.product_vision import analyze_product_images  # noqa: E402

_TEST_URL = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


async def run_diagnose(*, full_call: bool) -> int:
    settings = get_settings()
    mode = "Vertex AI" if gemini_use_vertex(settings) else "AI Studio"
    print("=== VidAU Flow 视觉识别诊断 ===")
    print(f"Gemini 模式: {mode}")
    print(f"已配置: {gemini_configured(settings)}")
    print(f"模型: {settings.gemini_text_model}")
    print(f"Vertex 项目: {settings.gemini_vertex_project or '(未设)'}")
    print(f"Nuwa Key: {'已配置' if settings.nuwa_api_key else '未配置'}")

    if not full_call:
        print("\n加 --call 可发起一次真实识别请求（消耗 API 配额）")
        return 0

    print("\n发起识别请求…")
    try:
        result = await analyze_product_images(
            settings,
            product_name="诊断测试",
            image_urls=[_TEST_URL],
        )
        provider = result.get("_vision_provider", settings.llm_provider)
        print(f"成功 — 提供方: {provider}")
        print(f"返回字段: {', '.join(k for k in result if not k.startswith('_'))}")
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"失败 — {exc}")
        return 1


def main() -> None:
    parser = argparse.ArgumentParser(description="诊断产品图 AI 识别链路")
    parser.add_argument("--call", action="store_true", help="发起真实 API 调用")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(run_diagnose(full_call=args.call)))


if __name__ == "__main__":
    main()
