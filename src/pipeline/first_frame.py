"""首帧交互图 — 用 Nano Banana（Gemini 图像模型）按产品参考图与分镜画面生成一张首帧，
供 Seedance 作为 image-to-video 的首帧输入，适合交互复杂、需精确还原细节的产品。"""

from __future__ import annotations

import base64
import mimetypes
import uuid
from pathlib import Path
from typing import Any

import httpx

from src.config import Settings, get_settings
from src.pipeline.brand_profile import BrandProfile
from src.pipeline.gemini_client import request_auth
from src.uploads import PRODUCT_IMAGES_DIR, UPLOADS_DIR, ensure_upload_dirs


def _first_frame_guide(brand: BrandProfile | None) -> str:
    """首帧画面约束：单帧静态构图、真实场景、产品细节精确、不做插电/纯色/环绕。
    品牌名（若有）拼入约束，无品牌时用中性措辞。"""
    bw = f"{brand.display} " if (brand and brand.has_brand) else ""
    return (
        "Generate ONE photorealistic still frame (not a collage) to serve as the opening "
        "frame of a 9:16 vertical short video.\n\n"
        "PRODUCT FIDELITY (critical):\n"
        f"- Match the {bw}hero unit's industrial design, color, proportions, button/port "
        "layout and on-unit LCD EXACTLY to the reference images.\n"
        "- If this is a KIT / bundle with multiple modules (e.g. Apex300 + Charger 2 + DC Hub), "
        "show ALL scripted components together in one coherent scene — main unit plus each "
        "accessory module with correct relative size, shape, labeling and placement.\n"
        "- Small accessories must remain clearly visible and identifiable (not cropped out, "
        "not merged into one blob). Use medium-wide framing so the full kit fits.\n"
        f"- Show ONLY the {bw}modules listed in the KIT WHITELIST below — exact count, "
        "no extra power stations, batteries, solar panels, expansion modules, or fridges.\n"
        f"- Do NOT invent extra {bw}products not in the whitelist.\n"
        f"- Lifestyle props (table, tent, trees) are fine; they must NOT be {bw}hardware.\n\n"
        "SCENE:\n"
        "- Realistic lifestyle environment with depth and props.\n"
        "- Clean stable single shot (no orbit, no motion blur).\n"
        "- BRAND LOGO only on product units — never on mugs, tents, clothing or props.\n"
        "- NO plugging into outlets, no port close-ups, no inserting plugs, no wall sockets.\n"
        "- NO text, captions, watermark or logo overlays on the image."
    )


def _build_first_frame_text(
    visual_prompt: str,
    *,
    product_name: str = "",
    product_specs: str = "",
    interaction_beats: list[dict[str, Any]] | None = None,
    product_understanding: dict[str, Any] | None = None,
    kit_constraint: dict[str, Any] | None = None,
    brand: BrandProfile | None = None,
) -> str:
    bw = f"{brand.display} " if (brand and brand.has_brand) else ""
    blocks = [_first_frame_guide(brand)]
    if product_name:
        blocks.append(f"PRODUCT / KIT: {product_name}")
    if kit_constraint:
        blocks.append(f"KIT WHITELIST (critical):\n{kit_constraint.get('constraint_text', '')}")
    if product_understanding:
        pu = product_understanding
        lines = []
        if pu.get("hero_product"):
            lines.append(f"Hero unit: {pu['hero_product']}")
        if pu.get("module_count"):
            lines.append(f"Exact {bw}module count in frame: {pu['module_count']}")
        modules = pu.get("allowed_modules") or []
        if modules:
            lines.append("Allowed modules ONLY: " + ", ".join(str(m) for m in modules))
        if pu.get("appearance_notes"):
            lines.append(f"Appearance: {pu['appearance_notes']}")
        acc = pu.get("allowed_accessories") or []
        if acc and not modules:
            lines.append("Kit accessories to include: " + ", ".join(str(a) for a in acc))
        if lines:
            blocks.append("PRODUCT UNDERSTANDING:\n" + "\n".join(lines))
    if product_specs.strip():
        blocks.append(
            "INTERFACE & INTERACTION NOTES (for accurate layout, NOT for plug-in close-ups):\n"
            + product_specs.strip()[:2000]
        )
    if interaction_beats:
        beat_lines = []
        for b in interaction_beats[:6]:
            t = b.get("time", "")
            action = b.get("action", "")
            if action:
                beat_lines.append(f"- [{t}] {action}")
        if beat_lines:
            blocks.append("INTERACTION BEATS TO SHOW:\n" + "\n".join(beat_lines))
    blocks.append("SCENE / INTERACTION TO RENDER:\n" + (visual_prompt or "").strip())
    return "\n\n".join(blocks)


def _image_part_from_url(image_url: str) -> dict[str, Any] | None:
    """本地 /uploads 图片转为 Gemini inline_data part。"""
    if not image_url or not image_url.startswith("/uploads/"):
        return None
    rel = image_url.removeprefix("/uploads/")
    path = UPLOADS_DIR / rel
    if not path.is_file():
        return None
    mime = mimetypes.guess_type(path.name)[0] or "image/jpeg"
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return {"inline_data": {"mime_type": mime, "data": data}}


def _first_frame_url(settings: Settings, model: str) -> str:
    """图像模型 generateContent 端点；Vertex 图像模型常需 global 区。"""
    from src.pipeline.gemini_client import gemini_use_vertex

    if gemini_use_vertex(settings):
        project = (settings.gemini_vertex_project or "").strip()
        if not project:
            raise RuntimeError("Vertex 模式需配置 GEMINI_VERTEX_PROJECT")
        location = (settings.gemini_vertex_location or "us-central1").strip()
        # 图像模型走 global 端点更稳（多数区域未部署）
        host = "aiplatform.googleapis.com"
        loc = "global"
        return (
            f"https://{host}/v1/projects/{project}/locations/{loc}/"
            f"publishers/google/models/{model}:generateContent"
        )
    return f"{settings.gemini_api_base.rstrip('/')}/models/{model}:generateContent"


def _extract_image_bytes(data: dict[str, Any]) -> tuple[bytes, str] | None:
    candidates = data.get("candidates") or []
    for cand in candidates:
        parts = (cand.get("content") or {}).get("parts") or []
        for part in parts:
            inline = part.get("inline_data") or part.get("inlineData")
            if inline and inline.get("data"):
                mime = inline.get("mime_type") or inline.get("mimeType") or "image/png"
                try:
                    return base64.b64decode(inline["data"]), mime
                except Exception:  # noqa: BLE001
                    continue
    return None


def _ext_for_mime(mime: str) -> str:
    return {
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/webp": ".webp",
    }.get(mime.split(";")[0].strip().lower(), ".png")


async def generate_first_frame_image(
    *,
    visual_prompt: str,
    product_image_urls: list[str],
    settings: Settings | None = None,
    file_stem: str = "",
    product_name: str = "",
    product_specs: str = "",
    interaction_beats: list[dict[str, Any]] | None = None,
    product_understanding: dict[str, Any] | None = None,
    kit_constraint: dict[str, Any] | None = None,
    brand: BrandProfile | None = None,
) -> str:
    """生成首帧图，返回本地 /uploads/products/xxx 路径。失败抛 RuntimeError。"""
    settings = settings or get_settings()
    ensure_upload_dirs()
    model = (settings.first_frame_model or "gemini-3-pro-image").strip()

    user_text = _build_first_frame_text(
        visual_prompt,
        product_name=product_name,
        product_specs=product_specs,
        interaction_beats=interaction_beats,
        product_understanding=product_understanding,
        kit_constraint=kit_constraint,
        brand=brand,
    )
    parts: list[dict[str, Any]] = [{"text": user_text}]
    for url in product_image_urls[:14]:
        part = _image_part_from_url(url)
        if part:
            parts.append(part)

    body: dict[str, Any] = {
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {
            "responseModalities": ["TEXT", "IMAGE"],
            "imageConfig": {
                "aspectRatio": settings.first_frame_aspect_ratio or "9:16",
                "imageSize": settings.first_frame_image_size or "2K",
            },
        },
    }

    url = _first_frame_url(settings, model)
    headers, params = request_auth(settings)
    async with httpx.AsyncClient(timeout=180) as client:
        resp = await client.post(url, headers=headers, params=params or None, json=body)
    if resp.is_error:
        detail = ""
        try:
            detail = resp.json().get("error", {}).get("message", "")
        except Exception:  # noqa: BLE001
            detail = (resp.text or "")[:300]
        raise RuntimeError(f"首帧图生成失败（{model} HTTP {resp.status_code}）：{detail[:300]}")

    extracted = _extract_image_bytes(resp.json())
    if not extracted:
        raise RuntimeError("首帧图生成失败：模型未返回图片数据")
    img_bytes, mime = extracted
    stem = file_stem or uuid.uuid4().hex
    filename = f"ff_{stem}{_ext_for_mime(mime)}"
    out = PRODUCT_IMAGES_DIR / filename
    out.write_bytes(img_bytes)
    return f"/uploads/products/{filename}"
