"""临时：验证产品图视觉识别链路。"""
import asyncio

from src.config import get_settings, load_prompt
from src.pipeline.product_vision import analyze_product_images

PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


async def main() -> None:
    settings = get_settings()
    print("gemini:", bool(settings.gemini_api_key), "nuwa:", bool(settings.nuwa_api_key))
    print("llm_provider:", settings.llm_provider, "fallback:", settings.llm_fallback_provider)
    system = load_prompt("product_vision_system")
    print("prompt loaded:", bool(system))
    result = await analyze_product_images(
        settings,
        product_name="Test",
        image_urls=[f"data:image/png;base64,{PNG_B64}"],
    )
    print("provider:", result.get("_vision_provider", settings.llm_provider))
    print("keys:", list(result.keys()))
    print("specs:", (result.get("product_specs_text") or "")[:200])


if __name__ == "__main__":
    asyncio.run(main())
