import base64
import json
import mimetypes
import uuid
from pathlib import Path

from fastapi import HTTPException, UploadFile

from src.config import ROOT

UPLOADS_DIR = ROOT / "data" / "uploads"
PRODUCT_IMAGES_DIR = UPLOADS_DIR / "products"
# Seedance 2.0 多模态参考：单张 <30MB，请求体 <64MB，1~9 张
ALLOWED_IMAGE_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".bmp",
    ".tif",
    ".tiff",
    ".gif",
    ".heic",
    ".heif",
}
MAX_IMAGE_BYTES = 30 * 1024 * 1024
MAX_UPLOAD_REQUEST_BYTES = 64 * 1024 * 1024
MAX_PRODUCT_IMAGES = 9
MIN_PRODUCT_IMAGES = 1
ALLOWED_IMAGE_FORMATS_LABEL = "JPEG、PNG、WEBP、BMP、TIFF、GIF、HEIC、HEIF"


def ensure_upload_dirs() -> None:
    PRODUCT_IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    (UPLOADS_DIR / "videos").mkdir(parents=True, exist_ok=True)
    (UPLOADS_DIR / "reference").mkdir(parents=True, exist_ok=True)


REFERENCE_VIDEOS_DIR = UPLOADS_DIR / "reference"
MAX_REFERENCE_VIDEO_BYTES_SEEDANCE = 50 * 1024 * 1024


def save_local_reference_video(path: Path) -> str:
    """Copy local mp4 into uploads/reference, return web path."""
    ensure_upload_dirs()
    if not path.is_file():
        raise FileNotFoundError(path)
    ext = path.suffix.lower()
    if ext not in _VIDEO_EXTS:
        raise ValueError(f"unsupported video: {ext}")
    data = path.read_bytes()
    if len(data) > MAX_REFERENCE_VIDEO_BYTES:
        raise ValueError("reference video exceeds 50MB Seedance limit")
    filename = f"{uuid.uuid4().hex}{ext}"
    dest = REFERENCE_VIDEOS_DIR / filename
    dest.write_bytes(data)
    return f"/uploads/reference/{filename}"


def resolve_video_url_for_api(video_url: str) -> str:
    """Local /uploads/reference/*.mp4 → public http(s) URL for Seedance reference_video.

    Seedance 云端无法拉取 data: URL 或 127.0.0.1；仅当配置了可公网访问的 asset base 时返回。
    """
    if not video_url:
        return ""
    if video_url.startswith(("http://", "https://")):
        return video_url
    from src.config import get_settings

    base = (get_settings().seedance_asset_public_base_url or "").strip().rstrip("/")
    if base and video_url.startswith("/uploads/"):
        return f"{base}{video_url}"
    return ""


def _ext_from_content_type(content_type: str) -> str:
    mapping = {
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "image/bmp": ".bmp",
        "image/x-ms-bmp": ".bmp",
        "image/tiff": ".tiff",
        "image/tif": ".tif",
        "image/gif": ".gif",
        "image/heic": ".heic",
        "image/heif": ".heif",
    }
    return mapping.get(content_type.split(";")[0].strip().lower(), "")


async def save_product_image(file: UploadFile) -> str:
    ensure_upload_dirs()

    content_type = (file.content_type or "").lower()
    ext = _ext_from_content_type(content_type)
    if not ext and file.filename:
        ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_IMAGE_EXTENSIONS:
        raise HTTPException(400, f"仅支持 {ALLOWED_IMAGE_FORMATS_LABEL} 图片")

    data = await file.read()
    if not data:
        raise HTTPException(400, "图片文件为空")
    if len(data) > MAX_IMAGE_BYTES:
        raise HTTPException(400, "单张图片不能超过 30MB（Seedance 限制）")

    filename = f"{uuid.uuid4().hex}{ext}"
    path = PRODUCT_IMAGES_DIR / filename
    path.write_bytes(data)
    return f"/uploads/products/{filename}"


_VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".webm", ".avi", ".mkv"}
MAX_REFERENCE_VIDEO_BYTES = 80 * 1024 * 1024


async def save_reference_video(file: UploadFile) -> tuple[str, bytes]:
    ensure_upload_dirs()
    ext = Path(file.filename or "").suffix.lower()
    if ext not in _VIDEO_EXTS:
        raise HTTPException(400, f"参考视频仅支持: {', '.join(sorted(_VIDEO_EXTS))}")
    data = await file.read()
    if not data:
        raise HTTPException(400, "参考视频文件为空")
    if len(data) > MAX_REFERENCE_VIDEO_BYTES:
        raise HTTPException(400, "参考视频不能超过 80MB")
    filename = f"{uuid.uuid4().hex}{ext}"
    path = REFERENCE_VIDEOS_DIR / filename
    path.write_bytes(data)
    return f"/uploads/reference/{filename}", data


def parse_product_image_urls(product: dict) -> list[str]:
    """从产品中解析图片 URL 列表（兼容旧版单图 image_url）。"""
    raw = product.get("image_urls_json", "")
    if raw:
        try:
            urls = json.loads(raw)
            if isinstance(urls, list):
                return [u for u in urls if isinstance(u, str) and u.strip()]
        except json.JSONDecodeError:
            pass
    image_url = product.get("image_url", "")
    return [image_url] if image_url else []


def product_image_db_fields(urls: list[str]) -> dict[str, str]:
    clean = [u.strip() for u in urls if isinstance(u, str) and u.strip()][:MAX_PRODUCT_IMAGES]
    return {
        "image_url": clean[0] if clean else "",
        "image_urls_json": json.dumps(clean, ensure_ascii=False),
    }


def enrich_product(product: dict) -> dict:
    from src.pipeline.product_conversion import resolve_conversion_method

    urls = parse_product_image_urls(product)
    product["image_urls"] = urls
    product["image_count"] = len(urls)
    product["conversion_method"] = resolve_conversion_method(product)
    product["specs_confirmed"] = bool(int(product.get("product_specs_confirmed") or 0))
    product["has_specs_draft"] = bool((product.get("product_specs_draft") or "").strip())
    return product


def resolve_image_urls_for_api(image_urls: list[str]) -> list[str]:
    return [resolved for u in image_urls if (resolved := resolve_image_url_for_api(u))]


def resolve_image_url_for_api(image_url: str) -> str:
    """将本地上传路径转为 Seedance 等外部 API 可用的 data URL。"""
    if not image_url:
        return ""
    if image_url.startswith(("http://", "https://", "data:")):
        return image_url
    if image_url.startswith("/uploads/"):
        rel = image_url.removeprefix("/uploads/")
        path = UPLOADS_DIR / rel
        if not path.is_file():
            return image_url
        ext = path.suffix.lower()
        mime = mimetypes.guess_type(path.name)[0] or {
            ".heic": "image/heic",
            ".heif": "image/heif",
            ".bmp": "image/bmp",
            ".tif": "image/tiff",
            ".tiff": "image/tiff",
        }.get(ext, "image/jpeg")
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        return f"data:{mime};base64,{encoded}"
    return image_url
