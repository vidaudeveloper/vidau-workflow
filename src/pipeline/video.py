"""视频生成 — Seedance 2.0（火山方舟）、主站 AI Video 或 OpenAI 占位。"""

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any

ProgressCallback = Callable[[dict[str, Any]], Awaitable[None]]

import httpx

from src.config import Settings
from src.pipeline.brand_profile import BrandProfile
from src.uploads import (
    MAX_PRODUCT_IMAGES,
    resolve_image_url_for_api,
    resolve_image_urls_for_api,
    resolve_video_url_for_api,
)

# 防止视频模型从参考图复刻人物/多余产品（品牌 Logo 规则由 BrandProfile 动态拼接）
SEEDANCE_FRAME_CONSTRAINT = (
    "Reference images are for matching the product's own industrial design only. "
    "Do NOT reproduce people, faces, full bodies, thumbs-up gestures, or any extra "
    "products/accessories from reference photos unless explicitly described below. "
    "Show only the scripted product and interactions. "
)

SEEDANCE_AUDIO_ONLY = (
    "AUDIO: Rich native English voiceover throughout—natural pacing, not silent. "
    "Voice must follow the spoken lines in the timeline below. "
    "NO burned-in subtitles or on-screen text (subtitles added in post). "
)

SEEDANCE_AUDIO_UGC = (
    "AUDIO: Energetic TikTok UGC native voiceover—casual creator talking to camera, "
    "fast confident delivery, viral ad energy, NOT corporate narrator or robotic AI voice. "
    "Match spoken lines below with natural lip-sync when face visible. "
    "NO burned-in subtitles or readable on-screen text (copy/subtitles added in post). "
)

SEEDANCE_PRODUCT_REF_VIDEO = (
    "REFERENCE VIDEO/FRAMES (product-only): Use reference_video or reference_image frames ONLY "
    "for horizontal sachet tear, powder color/texture, packaging. "
    "DO NOT copy people, faces, wardrobe, background, plot from reference media. "
    "Scripted creator/scene must follow the text prompt."
)

SEEDANCE_VISUAL_GRAPHICS = (
    "ON-SCREEN GRAPHICS: Icon/sticker graphics ONLY—red down-arrow, sale-badge shape, "
    "sparkle/star stickers, pointing hand graphic. "
    "NO readable text, NO letters, NO words, NO captions, NO subtitles, NO title cards "
    "in the video frame; marketing copy is voiceover + post-production subtitles only. "
    "Product packaging printed text from reference images is OK on the product itself."
)

SEEDANCE_SCENE_AND_EDIT = (
    "SCENE: Realistic lifestyle environment required—kitchen marble counter with cabinets and appliances, "
    "garage workshop with pegboard tools, or outdoor camping table with tent/trees. "
    "NEVER solid-color, plain white/gray studio, gradient, or empty void backgrounds. "
    "EDITING: Max 2 held beats per 15s segment; each beat 5-8 seconds; slow smooth static or gentle push-in; "
    "one continuous scene per segment; NO rapid jump cuts or 1-3 second flash cuts. "
    "BANNED VISUALS: NO plugging cables into wall outlets or product ports; NO AC/USB/RV port close-ups; "
    "NO hands inserting plugs; NO wall sockets; NO extension cord plug-in demos. "
    "Show the whole product unit in scene, LED screen, power button, or ambient usage context only. "
)

SEEDANCE_UGC_SCENE_AND_EDIT = (
    "STYLE: Authentic North American TikTok viral UGC ad—handheld smartphone energy, "
    "slight natural movement, relatable US/Canada creator vibe, NOT stiff AI mannequin or polished TV commercial. "
    "CREATOR: Young NA creator talking to camera OR POV hands demo; natural micro-expressions; "
    "casual denim/hoodie airport travel aesthetic; avoid uncanny faces, frozen poses, obvious CGI humans. "
    "SCENE: Real lived-in airport/home/car; ring light or daylight; messy-real props OK. "
    "EDITING: Hook in first 1-2 seconds; punchy 2-4s micro-beats; 4-6 cuts per 15s; "
    "TikTok viral pacing—fast, energetic, scroll-stopping; NO slow 5-8s static holds. "
    "CTA ENDING (11-15s): product on suitcase, blurred airport bg, red down-arrow sticker/icon only "
    "(NO readable CTA text on screen—urgency is voiceover only). "
    "BANNED: corporate slow-mo product orbit, empty studio, stiff presenter, robotic delivery, "
    "on-screen marketing text. "
)

SEEDANCE_VISUAL_ONLY = (
    "AUDIO: Silent video — no dialogue, no voiceover, no narration. "
    "Only subtle ambient room tone if needed. "
    "NO lip-sync, NO spoken words, NO on-screen text or subtitles (voiceover added in post-production). "
)

SEEDANCE_NO_SUBTITLE_NEGATIVE = (
    "burned-in subtitles, on-screen captions, closed captions, subtitles, "
    "readable text, letters, words, typography, title cards, lower thirds, "
    "text overlays, caption bars, white text overlay, promotional text on screen, "
    "misspelled text, random letters on screen, marketing copy on screen"
)

SEEDANCE_VISUAL_NEGATIVE = (
    "solid color background, plain white background, empty studio, gradient backdrop, "
    "stiff AI presenter, mannequin face, uncanny valley, robotic frozen pose, "
    "corporate TV commercial, slow cinematic product orbit, "
    "plugging into outlet, inserting plug, hands plugging cable, wall socket, "
    "AC outlet close-up, port close-up, USB port close-up, cable plugged into unit, "
    "wrong outlets, invented ports, European Schuko outlets, floating product on void, "
    "brand logo on mug, logo on cup, logo on clothing, logo on tent, logo on backpack, "
    "third-party logos, mountain logo on drinkware, branded props, watermark, "
    "TikTok logo, TikTok watermark, Douyin logo, social media app icon, platform UI overlay, "
    "360 degree orbit, orbiting camera, camera circling product, turntable spin, "
    "arc shot around product, full rotation around subject"
)


def _scene_edit_block(*, ugc: bool) -> str:
    return SEEDANCE_UGC_SCENE_AND_EDIT if ugc else SEEDANCE_SCENE_AND_EDIT


def build_seedance_prompt(
    prompt: str,
    *,
    voiceover_script: list[dict[str, Any]] | None = None,
    negative_prompt: str = "",
    voice_profile: str = "",
    generate_audio: bool = True,
    kit_constraint_text: str = "",
    brand: BrandProfile | None = None,
    ugc_style: bool | None = None,
    has_product_ref_video: bool = False,
) -> str:
    from src.config import get_settings

    brand = brand or BrandProfile()
    settings = get_settings()
    ugc = settings.seedance_ugc_style if ugc_style is None else ugc_style
    frame_constraint = SEEDANCE_FRAME_CONSTRAINT + brand.logo_rule_en()
    if ugc:
        frame_constraint = (
            "Reference images lock product design only. Creator/talent appearance comes from the "
            "script—natural UGC creator on camera is encouraged when scripted. "
            + brand.logo_rule_en()
        )
    parts = [frame_constraint, _scene_edit_block(ugc=ugc), SEEDANCE_VISUAL_GRAPHICS]
    if has_product_ref_video:
        parts.append(SEEDANCE_PRODUCT_REF_VIDEO)
    if kit_constraint_text.strip():
        parts.append(kit_constraint_text.strip())
    if generate_audio:
        if voice_profile.strip():
            parts.append(f"VOICE PERSONA (match account persona): {voice_profile.strip()}")
        parts.append(SEEDANCE_AUDIO_UGC if ugc else SEEDANCE_AUDIO_ONLY)
    else:
        parts.append(SEEDANCE_VISUAL_ONLY)
    parts.append(prompt.strip())
    if generate_audio and voiceover_script:
        lines = []
        for item in voiceover_script:
            t = item.get("time", "")
            spoken = item.get("spoken") or item.get("voiceover", "")
            if spoken:
                lines.append(f'[{t}] Spoken line (voiceover only): "{spoken}"')
        if lines:
            parts.append(
                "VOICEOVER SCRIPT TIMELINE (audio must match these lines; do not render as on-screen text):\n"
                + "\n".join(lines)
            )
    avoid = negative_prompt.strip()
    if avoid:
        parts.append(f"AVOID: {avoid}")
    parts.append(
        f"AVOID: {SEEDANCE_NO_SUBTITLE_NEGATIVE}, {SEEDANCE_VISUAL_NEGATIVE}, "
        f"{brand.negative_logo_clause()}"
    )
    return "\n\n".join(parts)


def _seedance_http_error(resp: httpx.Response) -> RuntimeError:
    """解析 Seedance HTTP 错误响应体，返回可读报错。"""
    detail = ""
    try:
        body = resp.json()
        err = body.get("error")
        if isinstance(err, dict):
            detail = err.get("message") or err.get("code") or json.dumps(err, ensure_ascii=False)
        elif isinstance(err, str):
            detail = err
        else:
            detail = body.get("message") or json.dumps(body, ensure_ascii=False)
    except Exception:
        detail = (resp.text or "").strip()
    if not detail:
        detail = resp.reason_phrase or "未知错误"
    return RuntimeError(f"Seedance API {resp.status_code}: {detail[:2000]}")


class VideoService:
    def __init__(self, settings: Settings):
        self.settings = settings

    def _use_platform_video(self) -> bool:
        if (self.settings.video_provider or "").lower() == "platform":
            return True
        return (self.settings.aigc_billing_mode or "none").lower() == "platform"

    async def generate(
        self,
        *,
        prompt: str,
        duration_sec: int,
        aspect_ratio: str,
        image_url: str = "",
        image_urls: list[str] | None = None,
        first_frame_url: str = "",
        voiceover_script: list[dict[str, Any]] | None = None,
        negative_prompt: str = "",
        voice_profile: str = "",
        kit_constraint_text: str = "",
        brand: BrandProfile | None = None,
        progress_callback: ProgressCallback | None = None,
        segment_label: str = "",
        platform_token: str = "",
        billing_biz_no: str = "",
        reference_video_urls: list[str] | None = None,
        product_reference_frames: bool = False,
    ) -> dict[str, Any]:
        urls = image_urls if image_urls is not None else ([image_url] if image_url else [])
        generate_audio = not (
            self.settings.tts_post_enabled and self.settings.tts_mute_seedance_audio
        )
        prompt_for_seedance = prompt
        if first_frame_url:
            prompt_for_seedance = (
                prompt.strip()
                + "\n\nFIRST-FRAME LOCK: Product appearance, kit layout and all accessory "
                "modules must match the provided opening frame exactly. "
                "Slow gentle push-in or hold — no 360 orbit, no turntable spin."
            )
        full_prompt = build_seedance_prompt(
            prompt_for_seedance,
            voiceover_script=voiceover_script if generate_audio else None,
            negative_prompt=negative_prompt,
            voice_profile=voice_profile if generate_audio else "",
            generate_audio=generate_audio,
            kit_constraint_text=kit_constraint_text,
            brand=brand,
            has_product_ref_video=bool(
                product_reference_frames
                or (
                    reference_video_urls
                    and any(resolve_video_url_for_api(u) for u in reference_video_urls)
                )
            ),
        )
        if self._use_platform_video():
            return await self._generate_platform(
                full_prompt,
                duration_sec,
                aspect_ratio,
                urls,
                first_frame_url=first_frame_url,
                platform_token=platform_token,
                progress_callback=progress_callback,
                segment_label=segment_label,
                billing_biz_no=billing_biz_no,
            )
        if self.settings.video_provider == "seedance":
            return await self._generate_seedance(
                full_prompt,
                duration_sec,
                aspect_ratio,
                urls,
                first_frame_url=first_frame_url,
                reference_video_urls=reference_video_urls,
                progress_callback=progress_callback,
                segment_label=segment_label,
            )
        return await self._generate_openai_placeholder(full_prompt, duration_sec, aspect_ratio)

    async def _generate_seedance(
        self,
        prompt: str,
        duration_sec: int,
        aspect_ratio: str,
        image_urls: list[str],
        *,
        first_frame_url: str = "",
        reference_video_urls: list[str] | None = None,
        progress_callback: ProgressCallback | None = None,
        segment_label: str = "",
    ) -> dict[str, Any]:
        if not self.settings.seedance_api_key:
            return {
                "status": "placeholder",
                "video_url": "",
                "message": "未配置 SEEDANCE_API_KEY，已排队待人工处理",
            }

        model = (
            self.settings.seedance_model_fast
            if self.settings.seedance_use_fast
            else self.settings.seedance_model
        )
        duration = max(4, min(15, duration_sec))
        resolution = "720p"

        base = self.settings.seedance_api_base.rstrip("/")
        headers = {
            "Authorization": f"Bearer {self.settings.seedance_api_key}",
            "Content-Type": "application/json",
        }
        content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
        # 首帧图（image-to-video）：作为视频第一帧，锁定开场构图与产品细节
        # Seedance 限制：first_frame 与 reference_image 不可混传 —— 细节保真交给 Nano Banana 首帧
        first_frame_resolved = resolve_image_url_for_api(first_frame_url) if first_frame_url else ""
        ref_videos = [
            v
            for u in (reference_video_urls or [])
            if (v := resolve_video_url_for_api(u))
        ]
        if first_frame_resolved:
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": first_frame_resolved},
                    "role": "first_frame",
                }
            )
        else:
            for resolved in ref_videos[:1]:
                content.append(
                    {
                        "type": "video_url",
                        "video_url": {"url": resolved},
                        "role": "reference_video",
                    }
                )
            resolved_images = resolve_image_urls_for_api(image_urls[:MAX_PRODUCT_IMAGES])
            for resolved in resolved_images:
                content.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": resolved},
                        "role": "reference_image",
                    }
                )

        from src.config import get_settings

        settings = get_settings()
        seedance_audio = not (
            settings.tts_post_enabled and settings.tts_mute_seedance_audio
        )
        payload = {
            "model": model,
            "content": content,
            "ratio": aspect_ratio,
            "duration": duration,
            "resolution": resolution,
            "watermark": False,
            "generate_audio": seedance_audio,
        }

        async with httpx.AsyncClient(timeout=60) as client:
            create = await client.post(
                f"{base}/api/v3/contents/generations/tasks",
                headers=headers,
                json=payload,
            )
            if create.status_code >= 400:
                raise _seedance_http_error(create)
            create_data = create.json()
            task_id = create_data.get("id") or create_data.get("task_id")
            if not task_id:
                raise RuntimeError(f"Seedance 未返回任务 ID: {create.text}")

            max_polls = 240

            async def _report(poll: int, api_status: str) -> None:
                if not progress_callback:
                    return
                await progress_callback(
                    {
                        "task_id": task_id,
                        "seedance_status": api_status or "submitted",
                        "poll": poll,
                        "max_polls": max_polls,
                        "segment": segment_label,
                    }
                )

            await _report(0, "submitted")

            # 15s 有声视频可能需 10+ 分钟，最多轮询约 20 分钟
            for i in range(max_polls):
                poll = await client.get(
                    f"{base}/api/v3/contents/generations/tasks/{task_id}",
                    headers=headers,
                )
                if poll.status_code >= 400:
                    raise _seedance_http_error(poll)
                data = poll.json()
                status = data.get("status", "")
                await _report(i + 1, status)

                if status == "succeeded":
                    video_url = (data.get("content") or {}).get("video_url", "")
                    if not video_url:
                        raise RuntimeError("Seedance 任务成功但未返回 video_url")
                    return {"status": "generated", "video_url": video_url, "task_id": task_id}

                if status in ("failed", "expired"):
                    err = data.get("error", {})
                    if isinstance(err, dict):
                        msg = err.get("message") or err.get("code") or json.dumps(err, ensure_ascii=False)
                    else:
                        msg = str(err) if err else f"Seedance 任务失败: {status}"
                    raise RuntimeError(msg)

                await asyncio.sleep(self.settings.seedance_poll_interval_sec)

        raise RuntimeError("Seedance 视频生成超时")

    async def _refund_platform_charge(
        self,
        *,
        billing_biz_no: str = "",
        order_sn: str = "",
    ) -> None:
        from src.platform.billing import billing_enabled, refund_video_charge

        if not billing_enabled(self.settings):
            return
        if not billing_biz_no.strip() and not order_sn.strip():
            return
        try:
            await refund_video_charge(biz_no=billing_biz_no, order_sn=order_sn)
        except Exception:  # noqa: BLE001
            pass

    async def _generate_platform(
        self,
        prompt: str,
        duration_sec: int,
        aspect_ratio: str,
        image_urls: list[str],
        *,
        first_frame_url: str = "",
        platform_token: str = "",
        progress_callback: ProgressCallback | None = None,
        segment_label: str = "",
        billing_biz_no: str = "",
    ) -> dict[str, Any]:
        if not platform_token.strip():
            return {
                "status": "placeholder",
                "video_url": "",
                "message": "主站出片缺少用户 token（请用主站登录后再审核出片）",
            }

        from src.platform.billing import VideoCharge, billing_enabled, charge_for_video_task
        from src.platform.client import build_video_task_params, get_platform_client

        duration = max(4, min(15, int(duration_sec)))
        generate_audio = not (
            self.settings.tts_post_enabled and self.settings.tts_mute_seedance_audio
        )
        resolved_ff = resolve_image_url_for_api(first_frame_url) if first_frame_url else ""
        ref_urls = (
            resolve_image_urls_for_api(image_urls[:MAX_PRODUCT_IMAGES])
            if not resolved_ff
            else None
        )
        task_params = build_video_task_params(
            prompt=prompt,
            model_name=self.settings.platform_video_model,
            duration=duration,
            ratio=aspect_ratio,
            resolution=self.settings.platform_video_resolution,
            generate_audio=generate_audio,
            first_frame_url=resolved_ff,
            reference_urls=ref_urls,
        )

        charge: VideoCharge | None = None
        if billing_enabled(self.settings):
            if not billing_biz_no.strip():
                raise RuntimeError("主站出片缺少 billing_biz_no")
            charge = await charge_for_video_task(
                platform_token,
                biz_no=billing_biz_no,
                task_params=task_params,
                settings=self.settings,
            )

        client = get_platform_client()
        charged = charge is not None
        try:
            task_id = await client.submit_video_task(platform_token, task_params)

            max_polls = 240
            poll_interval = float(self.settings.platform_video_poll_interval_sec or 5.0)

            async def _report(poll: int, api_status: str) -> None:
                if not progress_callback:
                    return
                await progress_callback(
                    {
                        "task_id": task_id,
                        "seedance_status": api_status,
                        "provider": "platform",
                        "poll": poll,
                        "max_polls": max_polls,
                        "segment": segment_label,
                    }
                )

            await _report(0, "submitted")

            for i in range(max_polls):
                snap = await client.poll_video_snapshot(platform_token, task_id)
                if snap.video_url:
                    await _report(i + 1, "succeeded")
                    result: dict[str, Any] = {
                        "status": "generated",
                        "video_url": snap.video_url,
                        "task_id": task_id,
                        "provider": "platform",
                    }
                    if charge:
                        result["charge"] = {
                            "biz_no": charge.biz_no,
                            "order_sn": charge.order_sn,
                            "coin_number": charge.coin_number,
                            "balance": charge.balance,
                        }
                    return result
                if snap.error and (snap.done or snap.item_status in (3, 4, -1)):
                    raise RuntimeError(snap.error or "主站视频生成失败")
                api_status = "running" if (snap.item_status == 1 or snap.progress) else "queued"
                await _report(i + 1, api_status)
                await asyncio.sleep(poll_interval)

            raise RuntimeError("主站视频生成超时")
        except Exception:
            if charged and charge:
                await self._refund_platform_charge(
                    billing_biz_no=charge.biz_no,
                    order_sn=charge.order_sn,
                )
            raise

    async def get_platform_task(self, task_id: str, platform_token: str) -> dict[str, Any]:
        from src.platform.client import get_platform_client, parse_video_task

        if not platform_token.strip():
            raise RuntimeError("缺少主站 token")
        payload = await get_platform_client().poll_video(platform_token, task_id)
        snap = parse_video_task(payload)
        status = "succeeded" if snap.video_url else "running"
        if snap.error and snap.done:
            status = "failed"
        return {
            "status": status,
            "content": {"video_url": snap.video_url},
            "error": {"message": snap.error} if snap.error else {},
            "provider": "platform",
            "snapshot": snap,
        }

    async def resume_platform_task(
        self,
        task_id: str,
        platform_token: str,
        *,
        progress_callback: ProgressCallback | None = None,
        segment_label: str = "",
        start_poll: int = 0,
        billing_biz_no: str = "",
        charge_order_sn: str = "",
    ) -> dict[str, Any]:
        if not platform_token.strip():
            return {
                "status": "placeholder",
                "video_url": "",
                "message": "主站出片缺少用户 token",
            }

        from src.platform.client import get_platform_client

        client = get_platform_client()
        max_polls = 240
        poll_interval = float(self.settings.platform_video_poll_interval_sec or 5.0)

        async def _report(poll: int, api_status: str) -> None:
            if not progress_callback:
                return
            await progress_callback(
                {
                    "task_id": task_id,
                    "seedance_status": api_status,
                    "provider": "platform",
                    "poll": poll,
                    "max_polls": max_polls,
                    "segment": segment_label,
                }
            )

        try:
            for i in range(start_poll, max_polls):
                snap = await client.poll_video_snapshot(platform_token, task_id)
                if snap.video_url:
                    await _report(i + 1, "succeeded")
                    return {
                        "status": "generated",
                        "video_url": snap.video_url,
                        "task_id": task_id,
                        "provider": "platform",
                    }
                if snap.error and (snap.done or snap.item_status in (3, 4, -1)):
                    raise RuntimeError(snap.error or "主站视频生成失败")
                await _report(i + 1, "running")
                await asyncio.sleep(poll_interval)

            raise RuntimeError("主站视频生成超时")
        except Exception:
            await self._refund_platform_charge(
                billing_biz_no=billing_biz_no,
                order_sn=charge_order_sn,
            )
            raise

    async def get_seedance_task(self, task_id: str) -> dict[str, Any]:
        """查询 Seedance 任务当前状态（单次，不轮询）。"""
        if not self.settings.seedance_api_key:
            raise RuntimeError("未配置 SEEDANCE_API_KEY")
        base = self.settings.seedance_api_base.rstrip("/")
        headers = {"Authorization": f"Bearer {self.settings.seedance_api_key}"}
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                f"{base}/api/v3/contents/generations/tasks/{task_id}",
                headers=headers,
            )
            if resp.status_code >= 400:
                raise _seedance_http_error(resp)
            return resp.json()

    async def resume_seedance_task(
        self,
        task_id: str,
        *,
        progress_callback: ProgressCallback | None = None,
        segment_label: str = "",
        start_poll: int = 0,
    ) -> dict[str, Any]:
        """从已有 task_id 继续轮询直至完成（用于服务重启后恢复）。"""
        if not self.settings.seedance_api_key:
            return {
                "status": "placeholder",
                "video_url": "",
                "message": "未配置 SEEDANCE_API_KEY",
            }
        base = self.settings.seedance_api_base.rstrip("/")
        headers = {"Authorization": f"Bearer {self.settings.seedance_api_key}"}
        max_polls = 240

        async def _report(poll: int, api_status: str) -> None:
            if not progress_callback:
                return
            await progress_callback(
                {
                    "task_id": task_id,
                    "seedance_status": api_status or "unknown",
                    "poll": poll,
                    "max_polls": max_polls,
                    "segment": segment_label,
                }
            )

        async with httpx.AsyncClient(timeout=60) as client:
            for i in range(start_poll, max_polls):
                poll = await client.get(
                    f"{base}/api/v3/contents/generations/tasks/{task_id}",
                    headers=headers,
                )
                if poll.status_code >= 400:
                    raise _seedance_http_error(poll)
                data = poll.json()
                status = data.get("status", "")
                await _report(i + 1, status)

                if status == "succeeded":
                    video_url = (data.get("content") or {}).get("video_url", "")
                    if not video_url:
                        raise RuntimeError("Seedance 任务成功但未返回 video_url")
                    return {"status": "generated", "video_url": video_url, "task_id": task_id}

                if status in ("failed", "expired"):
                    err = data.get("error", {})
                    if isinstance(err, dict):
                        msg = err.get("message") or err.get("code") or json.dumps(err, ensure_ascii=False)
                    else:
                        msg = str(err) if err else f"Seedance 任务失败: {status}"
                    raise RuntimeError(msg)

                await asyncio.sleep(self.settings.seedance_poll_interval_sec)

        raise RuntimeError("Seedance 视频生成超时")

    async def _generate_openai_placeholder(
        self, prompt: str, duration_sec: int, aspect_ratio: str
    ) -> dict[str, Any]:
        if not self.settings.video_api_key:
            return {
                "status": "placeholder",
                "video_url": "",
                "message": "未配置 VIDEO_API_KEY，已排队待人工处理",
            }

        async with httpx.AsyncClient(timeout=300) as client:
            resp = await client.post(
                f"{self.settings.video_api_base.rstrip('/')}/videos/generations",
                headers={"Authorization": f"Bearer {self.settings.video_api_key}"},
                json={
                    "model": self.settings.video_model,
                    "prompt": prompt,
                    "duration": duration_sec,
                    "aspect_ratio": aspect_ratio,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            return {
                "status": "generated",
                "video_url": data.get("url") or data.get("data", [{}])[0].get("url", ""),
                "raw": data,
            }
