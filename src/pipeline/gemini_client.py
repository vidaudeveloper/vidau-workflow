"""Gemini generateContent — 支持 AI Studio 与 Vertex AI。"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

import httpx

from src.config import ROOT, Settings

_TOKEN_CACHE: dict[str, tuple[str, float]] = {}
_ADC_CACHE_KEY = "__vertex_adc__"
_DEFAULT_VERTEX_SA = ROOT / "config" / "gemini-vertex-sa.json"
_VERTEX_SCOPES = ("https://www.googleapis.com/auth/cloud-platform",)


def gemini_use_vertex(settings: Settings) -> bool:
    if getattr(settings, "gemini_use_vertex", False):
        return True
    base = (settings.gemini_api_base or "").rstrip("/")
    return "aiplatform.googleapis.com" in base


def _resolve_credentials_path(credentials: str) -> Path:
    path = Path(credentials)
    if path.is_file():
        return path
    return ROOT / credentials


def vertex_credentials_candidates(settings: Settings) -> list[Path]:
    seen: set[str] = set()
    out: list[Path] = []
    for raw in (
        (settings.gemini_vertex_credentials or "").strip(),
        os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "").strip(),
        str(_DEFAULT_VERTEX_SA),
    ):
        if not raw:
            continue
        path = _resolve_credentials_path(raw)
        key = str(path.resolve()) if path.exists() else str(path)
        if key in seen:
            continue
        seen.add(key)
        out.append(path)
    return out


def resolve_vertex_credentials_path(settings: Settings) -> Path | None:
    for path in vertex_credentials_candidates(settings):
        if path.is_file():
            return path
    return None


def vertex_adc_available() -> bool:
    """GCE / Workload Identity 默认凭据，无需本地 SA JSON。"""
    now = time.time()
    cached = _TOKEN_CACHE.get(_ADC_CACHE_KEY)
    if cached and cached[1] > now + 60:
        return bool(cached[0])
    try:
        import google.auth
        import google.auth.transport.requests

        creds, _ = google.auth.default(scopes=list(_VERTEX_SCOPES))
        if not creds.valid:
            creds.refresh(google.auth.transport.requests.Request())
        ok = bool(creds.token)
    except Exception:
        ok = False
    _TOKEN_CACHE[_ADC_CACHE_KEY] = ("1" if ok else "", now + 300)
    return ok


def _vertex_adc_access_token() -> str:
    token_key = f"{_ADC_CACHE_KEY}:token"
    now = time.time()
    cached = _TOKEN_CACHE.get(token_key)
    if cached and cached[1] > now + 60:
        return cached[0]

    import google.auth
    import google.auth.transport.requests

    creds, _ = google.auth.default(scopes=list(_VERTEX_SCOPES))
    if not creds.valid:
        creds.refresh(google.auth.transport.requests.Request())
    token = creds.token or ""
    _TOKEN_CACHE[token_key] = (token, now + 3500)
    return token


def gemini_configured(settings: Settings) -> bool:
    if gemini_use_vertex(settings):
        if resolve_vertex_credentials_path(settings):
            return True
        if (settings.gemini_vertex_project or "").strip() and vertex_adc_available():
            return True
        return bool((settings.gemini_api_key or "").strip())
    return bool((settings.gemini_api_key or "").strip())


def nuwa_configured(settings: Settings) -> bool:
    return bool((settings.nuwa_api_key or "").strip())


def openai_configured(settings: Settings) -> bool:
    return bool((settings.openai_api_key or "").strip())


def llm_ready(settings: Settings) -> bool:
    """批次/脚本生成前：主通道或 fallback 至少有一个可用 LLM。"""
    provider = (settings.llm_provider or "gemini").strip().lower()
    fallback = (settings.llm_fallback_provider or "").strip().lower()
    if provider == "gemini" and gemini_configured(settings):
        return True
    if provider == "nuwa" and nuwa_configured(settings):
        return True
    if provider == "openai" and openai_configured(settings):
        return True
    if fallback == "nuwa" and nuwa_configured(settings):
        return True
    if fallback == "openai" and openai_configured(settings):
        return True
    return False


def generate_content_url(settings: Settings, model: str) -> str:
    if gemini_use_vertex(settings):
        location = (settings.gemini_vertex_location or "us-central1").strip()
        project = (settings.gemini_vertex_project or "").strip()
        if not project:
            raise RuntimeError("Vertex 模式需配置 GEMINI_VERTEX_PROJECT")
        return (
            f"https://{location}-aiplatform.googleapis.com/v1/"
            f"projects/{project}/locations/{location}/publishers/google/models/"
            f"{model}:generateContent"
        )
    return f"{settings.gemini_api_base.rstrip('/')}/models/{model}:generateContent"


def _vertex_access_token(credentials_path: Path) -> str:
    key = str(credentials_path.resolve())
    now = time.time()
    cached = _TOKEN_CACHE.get(key)
    if cached and cached[1] > now + 60:
        return cached[0]

    from google.oauth2 import service_account
    import google.auth.transport.requests

    creds = service_account.Credentials.from_service_account_file(
        key,
        scopes=["https://www.googleapis.com/auth/cloud-platform"],
    )
    creds.refresh(google.auth.transport.requests.Request())
    token = creds.token or ""
    _TOKEN_CACHE[key] = (token, now + 3500)
    return token


def request_auth(settings: Settings) -> tuple[dict[str, str], dict[str, str]]:
    headers: dict[str, str] = {}
    params: dict[str, str] = {}

    if gemini_use_vertex(settings):
        resolved = resolve_vertex_credentials_path(settings)
        if resolved is not None:
            headers["Authorization"] = f"Bearer {_vertex_access_token(resolved)}"
            return headers, params
        if (settings.gemini_vertex_project or "").strip() and vertex_adc_available():
            headers["Authorization"] = f"Bearer {_vertex_adc_access_token()}"
            return headers, params
        api_key = (settings.gemini_api_key or "").strip()
        if api_key:
            headers["x-goog-api-key"] = api_key
            return headers, params
        raise RuntimeError(
            "Vertex 模式需 config/gemini-vertex-sa.json、GOOGLE_APPLICATION_CREDENTIALS、"
            "GCP 默认凭据（ADC）或 GEMINI_API_KEY"
        )

    api_key = (settings.gemini_api_key or "").strip()
    if api_key:
        params["key"] = api_key
    return headers, params


def post_generate_content_sync(
    settings: Settings,
    model: str,
    body: dict[str, Any],
    *,
    timeout: float = 180,
) -> httpx.Response:
    url = generate_content_url(settings, model)
    headers, params = request_auth(settings)
    with httpx.Client(timeout=timeout) as client:
        return client.post(url, headers=headers, params=params or None, json=body)


async def post_generate_content(
    client: httpx.AsyncClient,
    settings: Settings,
    model: str,
    body: dict[str, Any],
) -> httpx.Response:
    url = generate_content_url(settings, model)
    headers, params = request_auth(settings)
    return await client.post(url, headers=headers, params=params or None, json=body)
