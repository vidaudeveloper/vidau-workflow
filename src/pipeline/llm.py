import asyncio
import json
import re
from typing import Any, Protocol

from openai import AsyncOpenAI

from src.config import Settings, load_prompt
from src.pipeline.gemini_client import gemini_configured
from src.pipeline.gemini_llm import GeminiLLMService
from src.pipeline.voiceover_budget import budget_hint_text
from src.pipeline.workflow_language import oral_language_instruction, script_system_prompt, storyboard_system_prompt


class LLMBackend(Protocol):
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
        duration_sec: int = 30,
        segment_strategy: str = "dual",
    ) -> dict[str, Any]: ...

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
        duration_sec: int = 30,
        segment_strategy: str = "dual",
    ) -> dict[str, Any]: ...

    async def generate_storyboard_prompt(self, script_payload: dict[str, Any]) -> dict[str, Any]: ...

    async def regenerate_storyboard_prompt(
        self, script_payload: dict[str, Any], review_note: str, previous_prompt: str
    ) -> dict[str, Any]: ...

    async def analyze_product_vision(
        self,
        *,
        system: str,
        user_text: str,
        user_parts: list[dict[str, Any]],
        image_parts: list[dict[str, Any]],
    ) -> dict[str, Any]: ...


def _extract_json(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return json.loads(text)


class OpenAILLMService:
    def __init__(self, settings: Settings):
        self.client = AsyncOpenAI(api_key=settings.openai_api_key)
        self.model = settings.openai_model

    async def _chat(self, system: str, user: str) -> dict[str, Any]:
        resp = await self.client.chat.completions.create(
            model=self.model,
            temperature=0.4,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            response_format={"type": "json_object"},
        )
        content = resp.choices[0].message.content or "{}"
        return _extract_json(content)

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

    async def analyze_product_vision(
        self,
        *,
        system: str,
        user_text: str,
        user_parts: list[dict[str, Any]],
        image_parts: list[dict[str, Any]],
    ) -> dict[str, Any]:
        content: list[dict[str, Any]] = [{"type": "text", "text": user_text}]
        for part in image_parts:
            blob = part.get("inline_data") or {}
            mime = blob.get("mime_type") or "image/jpeg"
            data = blob.get("data") or ""
            if not data:
                continue
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime};base64,{data}"},
                }
            )
        resp = await self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": content},
            ],
            response_format={"type": "json_object"},
            temperature=0.2,
        )
        text = resp.choices[0].message.content or "{}"
        return _extract_json(text)


class NuwaLLMService(OpenAILLMService):
    def __init__(self, settings: Settings):
        self.client = AsyncOpenAI(
            api_key=settings.nuwa_api_key,
            base_url=settings.nuwa_api_base.rstrip("/"),
        )
        self.model = settings.nuwa_model


def _build_backend(settings: Settings, provider: str) -> LLMBackend:
    if provider == "gemini":
        if not gemini_configured(settings):
            raise ValueError("未配置 GEMINI_API_KEY 或 Vertex 凭据（GEMINI_VERTEX_CREDENTIALS）")
        return GeminiLLMService(settings)
    if provider == "nuwa":
        if not settings.nuwa_api_key:
            raise ValueError("未配置 NUWA_API_KEY")
        return NuwaLLMService(settings)
    if not settings.openai_api_key:
        raise ValueError("未配置 OPENAI_API_KEY")
    return OpenAILLMService(settings)


class LLMService:
    """主提供商失败时自动切换 fallback。"""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._primary = _build_backend(settings, settings.llm_provider)
        self._fallback: LLMBackend | None = None
        fb = settings.llm_fallback_provider.strip()
        if fb and fb != settings.llm_provider:
            try:
                self._fallback = _build_backend(settings, fb)
            except ValueError:
                self._fallback = None

    @staticmethod
    def _fmt_err(err: Exception) -> str:
        text = str(err).strip()
        return f"{type(err).__name__}: {text}" if text else type(err).__name__

    async def _call_with_retry(
        self, backend: LLMBackend, method: str, *args: Any, **kwargs: Any
    ) -> dict[str, Any]:
        """单个后端自动重试，应对偶发超时/限流/空错误。"""
        fn = getattr(backend, method)
        attempts = max(1, self.settings.llm_retry_attempts + 1)
        backoff = max(0.0, self.settings.llm_retry_backoff_sec)
        last_err: Exception | None = None
        for i in range(attempts):
            try:
                return await fn(*args, **kwargs)
            except Exception as err:  # noqa: BLE001
                last_err = err
                if i < attempts - 1:
                    await asyncio.sleep(backoff * (i + 1))
        assert last_err is not None
        raise last_err

    async def _call(self, method: str, *args: Any, **kwargs: Any) -> dict[str, Any]:
        try:
            return await self._call_with_retry(self._primary, method, *args, **kwargs)
        except Exception as primary_err:  # noqa: BLE001
            if not self._fallback:
                raise RuntimeError(
                    f"主 LLM（{self.settings.llm_provider}）失败"
                    f"（已重试 {self.settings.llm_retry_attempts} 次）: {self._fmt_err(primary_err)}"
                ) from primary_err
            try:
                return await self._call_with_retry(self._fallback, method, *args, **kwargs)
            except Exception as fallback_err:  # noqa: BLE001
                raise RuntimeError(
                    f"主 LLM（{self.settings.llm_provider}）失败: {self._fmt_err(primary_err)}；"
                    f"备用（{self.settings.llm_fallback_provider}）也失败: {self._fmt_err(fallback_err)}"
                ) from fallback_err

    async def generate_script(self, **kwargs: Any) -> dict[str, Any]:
        return await self._call("generate_script", **kwargs)

    async def regenerate_script(self, **kwargs: Any) -> dict[str, Any]:
        return await self._call("regenerate_script", **kwargs)

    async def generate_storyboard_prompt(self, script_payload: dict[str, Any]) -> dict[str, Any]:
        return await self._call("generate_storyboard_prompt", script_payload)

    async def regenerate_storyboard_prompt(
        self, script_payload: dict[str, Any], review_note: str, previous_prompt: str
    ) -> dict[str, Any]:
        return await self._call(
            "regenerate_storyboard_prompt", script_payload, review_note, previous_prompt
        )

    async def _analyze_product_vision_backend(
        self,
        backend: LLMBackend,
        *,
        system: str,
        user_text: str,
        user_parts: list[dict[str, Any]],
        image_parts: list[dict[str, Any]],
    ) -> dict[str, Any]:
        if isinstance(backend, GeminiLLMService):
            return await backend.analyze_product_vision(system=system, user_parts=user_parts)
        return await backend.analyze_product_vision(
            system=system,
            user_text=user_text,
            user_parts=user_parts,
            image_parts=image_parts,
        )

    async def analyze_product_vision(
        self,
        *,
        system: str,
        user_text: str,
        user_parts: list[dict[str, Any]],
        image_parts: list[dict[str, Any]],
    ) -> dict[str, Any]:
        kwargs = {
            "system": system,
            "user_text": user_text,
            "user_parts": user_parts,
            "image_parts": image_parts,
        }
        try:
            return await self._analyze_product_vision_backend(self._primary, **kwargs)
        except Exception as primary_err:  # noqa: BLE001
            if not self._fallback:
                raise
            try:
                result = await self._analyze_product_vision_backend(self._fallback, **kwargs)
                result["_vision_provider"] = self.settings.llm_fallback_provider
                return result
            except Exception:
                raise primary_err from None

    async def analyze_intake_materials(
        self,
        *,
        system: str,
        user_parts: list[dict[str, Any]],
    ) -> dict[str, Any]:
        for backend in (self._primary, self._fallback):
            if isinstance(backend, GeminiLLMService):
                return await backend.analyze_intake_materials(
                    system=system, user_parts=user_parts
                )
        raise RuntimeError("参考素材解析需要 Gemini / Vertex 多模态能力（PDF / 视频）")
