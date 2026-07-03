"""Gemini 文本生成 — 用法对齐 vidau-template-generator/src/api/gemini.ts"""

import asyncio
import json
import re
from typing import Any

import httpx

from src.config import Settings, load_prompt
from src.pipeline.gemini_client import gemini_use_vertex, post_generate_content
from src.pipeline.voiceover_budget import budget_hint_text
from src.pipeline.workflow_language import oral_language_instruction, script_system_prompt, storyboard_system_prompt

GEMINI_MODEL_FALLBACKS = (
    "gemini-2.0-flash-lite",
    "gemini-2.5-flash",
    "gemini-2.5-pro",
)


def _extract_json(text: str) -> dict[str, Any]:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return json.loads(text)


def _gemini_error_message(resp: httpx.Response, settings: Settings | None = None) -> str:
    try:
        data = resp.json()
        msg = data.get("error", {}).get("message") or resp.text[:200]
    except Exception:  # noqa: BLE001
        msg = resp.text[:200]
    lower = msg.lower()
    if resp.status_code == 429 or "quota" in lower:
        backend = "Vertex AI" if settings and gemini_use_vertex(settings) else "Google AI Studio"
        return (
            f"Gemini API 配额已用尽或触发限流（429）— 当前走 {backend}。"
            "请检查 GCP 项目配额/账单，或更换 Key/服务账号。"
            f" 原始信息: {msg[:120]}"
        )
    return msg


class GeminiLLMService:
    def __init__(self, settings: Settings):
        self.settings = settings
        models = [settings.gemini_text_model, *GEMINI_MODEL_FALLBACKS]
        seen: set[str] = set()
        self.models = [m for m in models if not (m in seen or seen.add(m))]

    async def _chat_with_parts(
        self,
        system: str,
        user_parts: list[dict[str, Any]],
        *,
        temperature: float = 0.4,
        timeout: float = 120,
    ) -> dict[str, Any]:
        last_err = "Gemini 调用失败"
        async with httpx.AsyncClient(timeout=timeout) as client:
            for model in self.models:
                for attempt in range(3):
                    body = {
                        "system_instruction": {"parts": [{"text": system}]},
                        "contents": [{"role": "user", "parts": user_parts}],
                        "generationConfig": {
                            "temperature": temperature,
                            "responseMimeType": "application/json",
                        },
                    }
                    resp = await post_generate_content(
                        client, self.settings, model, body
                    )
                    if resp.status_code == 429:
                        wait = 2 ** attempt * 2
                        last_err = f"Gemini 限流 ({model})，等待 {wait}s 后重试"
                        await asyncio.sleep(wait)
                        continue
                    if resp.status_code >= 500:
                        last_err = _gemini_error_message(resp, self.settings)
                        await asyncio.sleep(2)
                        continue
                    if resp.is_error:
                        last_err = _gemini_error_message(resp, self.settings)
                        if "is not found" in last_err.lower():
                            break
                        continue

                    data = resp.json()
                    candidates = data.get("candidates", [])
                    if not candidates:
                        last_err = f"Gemini 返回空结果: {data}"
                        break
                    parts = candidates[0].get("content", {}).get("parts", [])
                    text = parts[0].get("text", "{}") if parts else "{}"
                    return _extract_json(text)

        raise RuntimeError(last_err)

    async def _chat(self, system: str, user: str) -> dict[str, Any]:
        return await self._chat_with_parts(system, [{"text": user}])

    async def analyze_product_vision(
        self,
        *,
        system: str,
        user_parts: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return await self._chat_with_parts(
            system, user_parts, temperature=0.2, timeout=180
        )

    async def analyze_intake_materials(
        self,
        *,
        system: str,
        user_parts: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return await self._chat_with_parts(
            system, user_parts, temperature=0.25, timeout=300
        )

    async def generate_script(
        self,
        *,
        product: str,
        direction: str,
        selling_points: str = "",
        product_specs: str = "",
        direction_description: str = "",
        pricing_context: str = "",
        account_context: str = "",
        conversion_context: str = "",
        difficulty_context: str = "",
        extra_instruction: str = "",
        variant_index: int = 1,
        language: str = "英语",
        brand_context: str = "",
        prompt_profile: str = "",
        duration_sec: int = 30,
        segment_strategy: str = "dual",
    ) -> dict[str, Any]:
        system = script_system_prompt(language, product=product, prompt_profile=prompt_profile)
        user = (
            f"产品: {product}\n"
            + (f"{brand_context}\n" if brand_context else "")
            + f"产品卖点: {selling_points or '见默认配置'}\n"
            f"产品外观与交互: {product_specs or '无（整机场景展示；禁止插插座/插口特写镜头）'}\n"
            f"价格信息: {pricing_context or '无'}\n"
            f"内容方向: {direction}\n"
            f"方向说明: {direction_description or '见默认配置'}\n"
            f"制作难度: {difficulty_context or '低级（纯产品展示、2-3镜、禁止插电镜头）'}\n"
            f"发布账号人设: {account_context or '通用品牌账号'}\n"
            f"产品转化方式（CTA 必须遵守）: {conversion_context or '视频挂链：引导点击视频下方商品链接购买'}\n"
            f"变体序号: {variant_index}（请与其他变体差异化 Hook 和场景）\n"
            f"补充指令: {extra_instruction or '无'}\n"
            f"{oral_language_instruction(language)}\n\n"
            f"{budget_hint_text(language, duration_sec=duration_sec, segment_strategy=segment_strategy)}"
        )
        return await self._chat(system, user)

    async def regenerate_script(
        self,
        *,
        product: str,
        direction: str,
        review_note: str,
        original_summary: str,
        account_context: str = "",
        conversion_context: str = "",
        selling_points: str = "",
        product_specs: str = "",
        pricing_context: str = "",
        difficulty_context: str = "",
        language: str = "英语",
        brand_context: str = "",
        prompt_profile: str = "",
        duration_sec: int = 30,
        segment_strategy: str = "dual",
    ) -> dict[str, Any]:
        system = script_system_prompt(language, product=product, prompt_profile=prompt_profile)
        regen = load_prompt("regenerate_script").format(
            review_note=review_note,
            original_summary=original_summary,
        )
        user = (
            f"产品: {product}\n内容方向: {direction}\n"
            + (f"{brand_context}\n" if brand_context else "")
            + f"产品卖点: {selling_points or '见默认配置'}\n"
            f"产品外观与交互: {product_specs or '无（整机场景展示；禁止插插座/插口特写镜头）'}\n"
            f"价格信息: {pricing_context or '无'}\n"
            f"制作难度: {difficulty_context or '低级'}\n"
            f"发布账号人设: {account_context or '通用品牌账号'}\n"
            f"产品转化方式（CTA 必须遵守）: {conversion_context or '视频挂链：引导点击视频下方商品链接购买'}\n"
            f"{oral_language_instruction(language)}\n\n"
            f"{regen}\n\n"
            f"{budget_hint_text(language, duration_sec=duration_sec, segment_strategy=segment_strategy)}"
        )
        return await self._chat(system, user)

    async def generate_storyboard_prompt(self, script_payload: dict[str, Any]) -> dict[str, Any]:
        language = script_payload.get("language", "英语")
        system = storyboard_system_prompt(
            language,
            product=script_payload.get("product"),
            payload=script_payload,
        )
        user = f"已审核脚本:\n{json.dumps(script_payload, ensure_ascii=False, indent=2)}"
        return await self._chat(system, user)

    async def regenerate_storyboard_prompt(
        self,
        script_payload: dict[str, Any],
        review_note: str,
        previous_prompt: str,
    ) -> dict[str, Any]:
        language = script_payload.get("language", "英语")
        system = storyboard_system_prompt(
            language,
            product=script_payload.get("product"),
            payload=script_payload,
        )
        user = (
            f"脚本:\n{json.dumps(script_payload, ensure_ascii=False)}\n\n"
            f"上一版 prompt 审核不通过。备注: {review_note}\n"
            f"上一版两段 prompt:\n{previous_prompt}\n"
            f"请调整后重新输出 JSON（含 prompt_part_a、prompt_part_b，各 15s）。"
        )
        return await self._chat(system, user)
