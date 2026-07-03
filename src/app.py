from contextlib import asynccontextmanager, AsyncExitStack
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.sessions import SessionMiddleware

from src.auth.access import (
    access_context,
    default_creator,
    ensure_batch_access,
    ensure_prompt_access,
    ensure_script_access,
    ensure_video_access,
)
from src.auth.deps import is_platform_mode, is_public_path, require_admin, require_user
from src.auth.password import hash_password, verify_password
from src.auth.seed import ensure_admin_user
from src.auth.test_account import is_test_user, normalize_login_email
from src.config import ROOT, get_settings
from src.platform.billing import InsufficientCreditsError
from src.platform.purchase import billing_public_meta
from src.pipeline.gemini_client import (
    gemini_configured,
    gemini_use_vertex,
    llm_ready,
    nuwa_configured,
    resolve_vertex_credentials_path,
    vertex_adc_available,
)
from src.config_sync import export_fixed_config, import_fixed_config
from src.config_csv_import import import_accounts_csv, import_directions_csv, import_products_csv
from src.util.locale_detect import detect_ui_locale
from src.db.database import get_db_path, init_db
from src.db.repository import Repository
from src.db.seed_cindy import seed_cindy_data
from src.pipeline.intake_formats import extract_video_url, intake_formats_public
from src.pipeline.intake_materials import analyze_intake_materials
from src.pipeline.orchestrator import WorkflowOrchestrator
from src.pipeline.product_conversion import resolve_conversion_method
from src.pipeline.canvas_state import (
    build_canvas_state,
    canvas_to_mermaid,
    canvas_to_svg,
)
from src.pipeline.reference_decompose import decompose_reference_video
from src.pipeline.reference_style_learn import learn_reference_style
from src.pipeline.workflow_blueprint import WorkflowBlueprint, assess_product_difficulty
from src.pipeline.workflow_service import (
    confirm_blueprint,
    create_blueprint_from_decomposition,
    get_confirmation_sheet,
    load_blueprint,
    save_blueprint,
)
from src.util.package_download import (
    build_board_download_filenames,
    build_board_package,
    build_delivery_zip,
    extract_audio_wav,
    local_video_path_from_url,
)
from src.hermes_skills_registry import build_skills_index, skill_md_path
from src.mcp_integration import init_mcp_http
from src.uploads import (
    MAX_PRODUCT_IMAGES,
    MAX_UPLOAD_REQUEST_BYTES,
    MIN_PRODUCT_IMAGES,
    UPLOADS_DIR,
    enrich_product,
    ensure_upload_dirs,
    parse_product_image_urls,
    product_image_db_fields,
    save_reference_video,
    save_product_image,
)

FRONTEND_DIR = ROOT / "frontend"
_NO_CACHE_HEADERS = {"Cache-Control": "no-cache, no-store, must-revalidate"}
PRODUCTS = [
    "Apex 300",
    "Elite 300",
    "FridgePower",
    "Elite 100 V2",
    "Elite 100 MiNi",
    "Apex300+B300K",
    "其他",
]
DIRECTIONS = [
    "①情感应急型",
    "②开箱实测型",
    "③场景对比型",
    "④极端天气应急型",
    "⑤功能解说型",
    "⑥日常融入生活型",
    "⑦用户回复答疑型",
    "⑧价格惊喜型",
    "⑨便携场景型",
    "⑩组合套餐型",
]

# To C 轻量事件缓冲（用于灰度期本地观察；重启后清空）
_TOC_METRICS_MAX = 500
_toc_metrics_events: list[dict[str, Any]] = []


import uuid

@asynccontextmanager
async def lifespan(_: FastAPI):
    import asyncio

    adflow_mcp, _mcp_http = init_mcp_http()
    async with AsyncExitStack() as stack:
        await stack.enter_async_context(adflow_mcp.session_manager.run())
        init_db()
        ensure_upload_dirs()
        ensure_admin_user(repo)
        # 初始数据迁移
        if not repo.list_products():
            for p in PRODUCTS:
                repo.create_product({"id": str(uuid.uuid4())[:8], "name": p})
        if not repo.list_directions():
            for d in DIRECTIONS:
                repo.create_direction({"id": str(uuid.uuid4())[:8], "name": d})
        seed_cindy_data()
        s = get_settings()
        from src.pipeline.gemini_client import gemini_use_vertex

        mode = "Vertex AI" if gemini_use_vertex(s) else "AI Studio"
        print(f"[VidAU Flow] Gemini: {mode}, configured={gemini_configured(s)}, model={s.gemini_text_model}")
        print("[VidAU Flow] MCP Streamable HTTP mounted at /mcp")
        asyncio.create_task(orch.recover_stuck_batches())
        asyncio.create_task(orch.recover_all_stuck_videos())
        yield


app = FastAPI(title="VidAU Flow", lifespan=lifespan)
_settings = get_settings()


@app.exception_handler(InsufficientCreditsError)
async def insufficient_credits_handler(_request: Request, exc: InsufficientCreditsError):
    from src.platform.purchase import agent_purchase_url

    return JSONResponse(
        status_code=402,
        content={
            "detail": str(exc),
            "code": "insufficient_credits",
            "coin": exc.coin,
            "needed": exc.needed,
            "purchase_url": agent_purchase_url(),
        },
    )


def _meta_billing() -> dict[str, Any]:
    return billing_public_meta(get_settings())


def _toc_config() -> dict[str, Any]:
    settings = get_settings()
    return {
        "default_language": settings.toc_default_language or "英语",
        "metrics_enabled": bool(settings.toc_metrics_enabled),
        "journey": "brief_or_url_to_first_ad",
        "cta": "创建第一条广告",
    }


def _toc_track(request: Request, event: str, properties: dict[str, Any] | None = None) -> None:
    settings = get_settings()
    if not settings.toc_metrics_enabled:
        return
    user = getattr(request.state, "user", None) or {}
    evt = {
        "ts": datetime.now(UTC).isoformat(),
        "event": event,
        "uid": str(user.get("id") or ""),
        "path": request.url.path,
        "properties": properties or {},
    }
    _toc_metrics_events.append(evt)
    if len(_toc_metrics_events) > _TOC_METRICS_MAX:
        del _toc_metrics_events[: len(_toc_metrics_events) - _TOC_METRICS_MAX]
    # 灰度期先打应用日志，后续可接入外部埋点系统
    print(f"[ToCMetric] {evt}")


def _cors_origins() -> list[str]:
    s = get_settings()
    if not s.auth_enabled:
        return ["*"]
    origins = {s.public_base_url.rstrip("/")}
    origins.add(f"http://127.0.0.1:{s.webhook_port}")
    origins.add(f"http://localhost:{s.webhook_port}")
    return sorted(origins)


app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


async def _platform_auth_guard(request: Request, call_next, settings):
    """platform 模式：读 token → 调主站解析 userId → 注入 request.state.user。"""
    from src.auth.platform_auth import extract_token, resolve_profile

    path = request.url.path
    token = extract_token(request, settings)
    profile = await resolve_profile(token) if token else None
    if not profile or not profile.user_id:
        if is_public_path(path):
            return await call_next(request)
        if path.startswith("/api/"):
            return JSONResponse({"detail": "未登录", "code": 40101}, status_code=401)
        if is_public_path(path):
            return await call_next(request)
        return RedirectResponse(url="/login", status_code=302)
    request.state.user = {
        "id": profile.user_id,
        "email": profile.email or "",
        "display_name": profile.nickname or profile.email or profile.user_id,
        "role": "user",
        "is_active": 1,
        "coin": profile.coin,
        "avatar": profile.avatar,
        "token": token,
    }
    response = await call_next(request)
    # 开发便利：URL ?token= 时写入 dev-token Cookie，后续请求免带
    if request.query_params.get("token") and not request.cookies.get(
        settings.platform_dev_token_cookie
    ):
        response.set_cookie(
            settings.platform_dev_token_cookie,
            token,
            httponly=True,
            samesite="lax",
            secure=settings.auth_cookie_secure and request.url.scheme == "https",
        )
    return response


def _platform_token_for_video(request: Request) -> str:
    """出片走主站 aiVideo 时，从请求提取 VidAu-Token（后台任务会持久化到 segment_urls_json）。"""
    settings = get_settings()
    vp = (settings.video_provider or "").lower()
    billing = (settings.aigc_billing_mode or "none").lower()
    if vp != "platform" and billing != "platform":
        return ""
    user = getattr(request.state, "user", None) or {}
    if isinstance(user, dict) and user.get("token"):
        return str(user["token"])
    from src.auth.platform_auth import extract_token

    return extract_token(request, settings) or ""


@app.middleware("http")
async def auth_guard(request: Request, call_next):
    settings = get_settings()
    if not settings.auth_enabled:
        return await call_next(request)
    path = request.url.path
    if is_public_path(path) or request.method == "OPTIONS":
        return await call_next(request)
    if (settings.auth_mode or "local").lower() == "platform":
        return await _platform_auth_guard(request, call_next, settings)
    user_id = request.session.get("user_id")
    user = repo.get_user(user_id) if user_id else None
    if not user or not user.get("is_active"):
        request.session.clear()
        if path.startswith("/api/"):
            return JSONResponse({"detail": "未登录"}, status_code=401)
        return RedirectResponse(url="/login", status_code=302)
    request.state.user = user
    return await call_next(request)


if _settings.auth_enabled:
    app.add_middleware(
        SessionMiddleware,
        secret_key=_settings.secret_key,
        https_only=_settings.auth_cookie_secure,
        same_site="lax",
    )

repo = Repository()
orch = WorkflowOrchestrator(repo)


def account_display_name(account_id: str) -> str:
    if not account_id:
        return "通用"
    acc = repo.get_account(account_id)
    if not acc:
        return account_id
    return (acc.get("display_name") or acc.get("username") or account_id).strip()


def enrich_from_script(target: dict[str, Any], script: dict | None) -> None:
    if not script:
        return
    target["product"] = script.get("product", "")
    target["direction"] = script.get("direction", "")
    target["account_name"] = account_display_name(script.get("account_id", ""))
    target["batch_id"] = script.get("batch_id", "")


class BatchCreate(BaseModel):
    product: str = "Elite 300"
    direction: str = "⑤功能解说型"
    count: int = Field(default=3, ge=1, le=20)
    extra_instruction: str = ""
    creator: str = ""
    difficulty_level: str = "低级"
    account_id: str = ""
    language: str = "英语"
    producer: str = ""
    use_first_frame: bool = False
    workflow_id: str = ""


class WorkflowBlueprintPatch(BaseModel):
    product_id: str = ""
    product_name: str = ""
    platform: str = ""
    goal: str = ""
    reference: dict[str, Any] | None = None
    video_spec: dict[str, Any] | None = None
    production: dict[str, Any] | None = None
    creative: dict[str, Any] | None = None
    batch: dict[str, Any] | None = None
    estimate: dict[str, Any] | None = None


class WorkflowBlueprintFromDecomp(BaseModel):
    decomposition_id: str
    product_id: str = ""
    product_name: str = ""
    reference_mode: str = "structure_clone"
    platform: str = "tiktok"
    goal: str = "traffic"
    patch: dict[str, Any] = Field(default_factory=dict)


class TocQuickGenerateRequest(BaseModel):
    brief: str = Field(min_length=2, max_length=2000)
    product: str = ""
    direction: str = ""
    language: str = ""
    source_url: str = ""
    reference_video_url: str = ""
    material_context: str = Field(default="", max_length=12000)
    count: int = Field(default=1, ge=1, le=3)
    creator: str = ""
    use_first_frame: bool = True


class TocQuickEstimateRequest(BaseModel):
    brief: str = Field(min_length=2, max_length=500)
    duration_sec: int = Field(default=15, ge=5, le=30)
    ratio: str = "9:16"
    resolution: str = "1080p"
    model_name: str = ""


class TocMetricEvent(BaseModel):
    event: str = Field(min_length=2, max_length=80)
    properties: dict[str, Any] = Field(default_factory=dict)


class TocScriptPatch(BaseModel):
    hook: str | None = None
    direction: str | None = None
    outline: str | None = None


class TocBranchRequest(BaseModel):
    node: str = Field(pattern="^(script|storyboard|video)$")
    create_branch: bool = True
    hook: str | None = None
    direction: str | None = None
    note: str = ""


class ScriptDeliveryUpdate(BaseModel):
    delivery_status: str | None = None
    delivery_feedback: str | None = None
    producer: str | None = None
    fa_flag: str | None = None


class AccountCreate(BaseModel):
    no: int = 0
    display_name: str
    username: str = ""
    language: str = "英语"
    blogger_type: str = ""
    positioning: str = ""
    content_directions: str = ""
    page_packaging: str = ""
    main_products: str = ""
    persona_style: str = ""
    avatar_desc: str = ""
    bio: str = ""


class AccountUpdate(BaseModel):
    no: int | None = None
    display_name: str | None = None
    username: str | None = None
    language: str | None = None
    blogger_type: str | None = None
    positioning: str | None = None
    content_directions: str | None = None
    page_packaging: str | None = None
    main_products: str | None = None
    persona_style: str | None = None
    avatar_desc: str | None = None
    bio: str | None = None


class FixedConfigImportBody(BaseModel):
    bundle: dict[str, Any]


class ReferenceDecompositionSeed(BaseModel):
    id: str
    source_url: str = ""
    source_filename: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)


class ScriptReview(BaseModel):
    status: str
    note: str = ""
    reviewer: str = ""


class PromptReview(BaseModel):
    status: str
    note: str = ""


class VideoUpdate(BaseModel):
    subtitle_status: str | None = None
    output_status: str | None = None
    video_url: str | None = None
    note: str | None = None


class ProductCreate(BaseModel):
    name: str
    brand: str = ""
    brand_pronunciation: str = ""
    image_url: str = ""
    image_urls: list[str] = Field(default_factory=list)
    product_specs: str = ""
    selling_points: str = ""
    daily_price: str = ""
    promo_price: str = ""
    purchase_link: str = ""
    listing_status: str = ""
    conversion_method: str = ""
    product_specs_confirmed: bool = False


class ProductUpdate(BaseModel):
    name: str | None = None
    brand: str | None = None
    brand_pronunciation: str | None = None
    image_url: str | None = None
    image_urls: list[str] | None = None
    product_specs: str | None = None
    selling_points: str | None = None
    daily_price: str | None = None
    promo_price: str | None = None
    purchase_link: str | None = None
    listing_status: str | None = None
    conversion_method: str | None = None
    product_specs_confirmed: bool | None = None


class ProductAnalyzeRequest(BaseModel):
    product_name: str = ""
    image_urls: list[str] = Field(default_factory=list)
    existing_specs: str = ""
    existing_selling_points: str = ""


class ProductConfirmSpecsRequest(BaseModel):
    product_specs: str
    selling_points: str = ""


def _normalize_product_image_urls(
    image_urls: list[str] | None, image_url: str | None = None
) -> list[str]:
    urls = [u.strip() for u in (image_urls or []) if u and u.strip()]
    if not urls and image_url and image_url.strip():
        urls = [image_url.strip()]
    return urls


def _validate_product_images(urls: list[str]) -> None:
    if len(urls) < MIN_PRODUCT_IMAGES:
        raise HTTPException(400, f"请至少上传 {MIN_PRODUCT_IMAGES} 张产品图")
    if len(urls) > MAX_PRODUCT_IMAGES:
        raise HTTPException(400, f"产品图最多 {MAX_PRODUCT_IMAGES} 张")


class DirectionCreate(BaseModel):
    name: str
    description: str = ""
    short_code: str = ""


class DirectionUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    short_code: str | None = None


class LoginBody(BaseModel):
    email: str
    password: str


class SsoCallbackBody(BaseModel):
    token: str


def _meta_sso(settings) -> dict[str, Any]:
    from src.auth.sso import sso_public_config

    return sso_public_config(settings)


def _platform_current_user(profile) -> dict[str, Any]:
    return {
        "id": profile.user_id,
        "email": profile.email or "",
        "display_name": profile.nickname or profile.email or profile.user_id,
        "role": "user",
        "is_active": True,
        "coin": profile.coin,
        "avatar": profile.avatar,
    }


class UserCreate(BaseModel):
    email: str
    password: str
    display_name: str = ""
    role: str = "editor"


class UserUpdate(BaseModel):
    email: str | None = None
    display_name: str | None = None
    role: str | None = None
    is_active: bool | None = None
    password: str | None = None


def _public_user(user: dict) -> dict:
    return {
        "id": user.get("id", ""),
        "email": user.get("email", ""),
        "display_name": user.get("display_name", ""),
        "role": user.get("role", "editor"),
        "is_active": bool(user.get("is_active", 1)),
        "is_test": is_test_user(user),
        "created_at": user.get("created_at", ""),
    }


@app.get("/api/user/me")
async def platform_user_me(request: Request):
    """platform 模式：返回当前主站用户（含积分 coin）。"""
    settings = get_settings()
    if not settings.auth_enabled or (settings.auth_mode or "local").lower() != "platform":
        # 非 platform 模式回退到本地用户信息
        user = require_user(request)
        return {
            "user_id": user.get("id", ""),
            "nickname": user.get("display_name", ""),
            "coin": 0,
            "avatar": "",
        }
    user = require_user(request)
    return {
        "user_id": user.get("id", ""),
        "nickname": user.get("display_name", ""),
        "coin": user.get("coin", 0),
        "avatar": user.get("avatar", ""),
    }


@app.post("/api/auth/login")
async def auth_login(body: LoginBody, request: Request):
    settings = get_settings()
    if settings.auth_enabled and (settings.auth_mode or "local").lower() == "platform":
        raise HTTPException(400, "当前为 VidAU 统一登录，请使用 SSO 登录")
    email = normalize_login_email(body.email)
    user = repo.get_user_by_email(email)
    if not user or not user.get("is_active"):
        raise HTTPException(401, "邮箱或密码错误")
    if not verify_password(body.password, user.get("password_hash", "")):
        raise HTTPException(401, "邮箱或密码错误")
    request.session["user_id"] = user["id"]
    result = _public_user(user)
    if result.get("is_test"):
        result["login_notice"] = (
            "当前为测试账号：仅能看到本账号创建的批次/脚本/成片，与正式账号数据不互通。"
        )
    return result


@app.post("/api/auth/logout")
async def auth_logout(request: Request):
    from src.auth.sso import sso_enabled

    request.session.clear()
    settings = get_settings()
    response = JSONResponse({"ok": True, "sso_logout": sso_enabled(settings)})
    if is_platform_mode(settings):
        response.delete_cookie(settings.platform_dev_token_cookie)
    return response


@app.get("/api/auth/sso/config")
async def sso_config():
    """前端初始化 VidauSSO SDK 所需配置（公开）。"""
    settings = get_settings()
    return _meta_sso(settings)


@app.post("/api/auth/sso/callback")
async def sso_callback(body: SsoCallbackBody, request: Request):
    """SSO 登录成功后，校验 token 并写入开发 Cookie（本地/跨子域兜底）。"""
    from src.auth.platform_auth import cache_platform_profile, resolve_profile
    from src.auth.sso import SsoError, profile_from_sso_user, sso_enabled, sso_user_from_verify, verify_sso_token

    settings = get_settings()
    if not settings.auth_enabled or not is_platform_mode(settings):
        raise HTTPException(400, "仅 platform 鉴权模式支持 SSO")
    token = (body.token or "").strip()
    if not token:
        raise HTTPException(400, "缺少 token")
    sso_data: dict = {}
    sso_user: dict = {}
    if sso_enabled(settings):
        try:
            sso_data = await verify_sso_token(token, settings)
            sso_user = sso_user_from_verify(sso_data)
        except SsoError as exc:
            raise HTTPException(401, str(exc)) from exc
    profile = await resolve_profile(token, settings)
    if not profile and sso_user:
        profile = profile_from_sso_user(sso_user)
    if not profile:
        raise HTTPException(401, "Token 无效或主站不可达")
    cache_platform_profile(token, profile, settings)
    session_token = str(
        sso_data.get("token") or sso_data.get("access_token") or sso_user.get("token") or ""
    ).strip()
    cookie_token = session_token or token
    response = JSONResponse(
        {
            "ok": True,
            "user_id": profile.user_id,
            "nickname": profile.nickname,
            "email": profile.email,
            "coin": profile.coin,
        }
    )
    if session_token and session_token != token:
        cache_platform_profile(session_token, profile, settings)
    cookie_secure = settings.auth_cookie_secure and request.url.scheme == "https"
    response.set_cookie(
        settings.platform_dev_token_cookie,
        cookie_token,
        httponly=True,
        samesite="lax",
        secure=cookie_secure,
    )
    return response


@app.get("/api/auth/me")
async def auth_me(request: Request):
    return _public_user(require_user(request))


@app.get("/api/users")
async def list_users(request: Request):
    require_admin(request)
    return repo.list_users()


@app.post("/api/users")
async def create_user(body: UserCreate, request: Request):
    require_admin(request)
    if body.role not in ("admin", "editor"):
        raise HTTPException(400, "role 须为 admin 或 editor")
    if repo.get_user_by_email(body.email):
        raise HTTPException(400, "邮箱已存在")
    uid = str(uuid.uuid4())
    repo.create_user(
        {
            "id": uid,
            "email": body.email,
            "password_hash": hash_password(body.password),
            "display_name": body.display_name or body.email.split("@")[0],
            "role": body.role,
            "is_active": 1,
        }
    )
    user = repo.get_user(uid)
    return _public_user(user or {})


@app.patch("/api/users/{user_id}")
async def update_user(user_id: str, body: UserUpdate, request: Request):
    require_admin(request)
    user = repo.get_user(user_id)
    if not user:
        raise HTTPException(404, "用户不存在")
    fields = body.model_dump(exclude_unset=True)
    password = fields.pop("password", None)
    if password:
        fields["password_hash"] = hash_password(password)
    if fields.get("role") and fields["role"] not in ("admin", "editor"):
        raise HTTPException(400, "role 须为 admin 或 editor")
    if fields.get("is_active") is not None:
        fields["is_active"] = 1 if fields["is_active"] else 0
    if fields.get("is_test") is not None:
        fields["is_test"] = 1 if fields["is_test"] else 0
    repo.update_user(user_id, fields)
    return {"ok": True}


@app.get("/api/meta")
async def meta(request: Request):
    settings = get_settings()
    platform_mode = settings.auth_enabled and (settings.auth_mode or "local").lower() == "platform"
    current_user = None
    if platform_mode:
        from src.auth.platform_auth import extract_token, resolve_profile

        token = extract_token(request, settings)
        profile = await resolve_profile(token) if token else None
        if profile and profile.user_id:
            current_user = _platform_current_user(profile)
    else:
        user_id = request.session.get("user_id") if settings.auth_enabled else None
        if user_id:
            user = repo.get_user(user_id)
            if user and user.get("is_active"):
                current_user = _public_user(user)
    products = repo.list_products()
    directions = repo.list_directions()
    accounts = repo.list_accounts()
    difficulties = repo.list_difficulty_levels()
    catalog = {
        "products": [
            {
                "id": p["id"],
                "name": p["name"],
                "image_count": len(parse_product_image_urls(p)),
                "conversion_method": resolve_conversion_method(p),
                "specs_confirmed": bool(int(p.get("product_specs_confirmed") or 0)),
            }
            for p in products
        ],
        "directions": [
            {"id": d["id"], "name": d["name"], "short_code": d.get("short_code", "")}
            for d in directions
        ],
        "accounts": [
            {
                "id": a["id"],
                "no": a.get("no", 0),
                "label": f"账号{a.get('no', 0)} · {a.get('display_name', '')}",
                "display_name": a.get("display_name", ""),
                "username": a.get("username", ""),
            }
            for a in accounts
        ],
        "conversion_methods": ["视频挂链", "Bio引流", "橱窗商品卡"],
        "difficulties": [{"id": d["id"], "name": d["name"]} for d in difficulties],
        "languages": ["英语", "西语", "中文"],
        "delivery_statuses": ["", "可审核", "ok"],
        "gemini_mode": "vertex" if gemini_use_vertex(settings) else "ai_studio",
        "gemini_configured": gemini_configured(settings),
        "gemini_vertex_creds_found": resolve_vertex_credentials_path(settings) is not None,
        "gemini_vertex_adc": vertex_adc_available() if gemini_use_vertex(settings) else False,
        "gemini_model": settings.gemini_text_model,
        "llm_provider": settings.llm_provider,
        "llm_fallback_provider": settings.llm_fallback_provider,
        "nuwa_configured": nuwa_configured(settings),
        "llm_ready": llm_ready(settings),
        "public_base_url": settings.public_base_url.rstrip("/"),
        "app_domain": settings.app_domain,
    }
    if settings.auth_enabled and not current_user:
        return {
            "auth_enabled": True,
            "auth_mode": "platform" if platform_mode else "local",
            "sso": _meta_sso(settings),
            "billing": _meta_billing(),
            "current_user": None,
            **catalog,
        }
    return {
        "auth_enabled": settings.auth_enabled,
        "auth_mode": "platform" if platform_mode else "local",
        "sso": _meta_sso(settings),
        "billing": _meta_billing(),
        "current_user": current_user,
        "database_path": str(get_db_path()),
        **catalog,
    }


@app.get("/api/billing/pricing")
async def billing_pricing():
    """Agent 套餐与购买链接（供前端展示 / 跳转 agent-price）。"""
    return _meta_billing()


def _first_product_name() -> str:
    products = repo.list_products()
    if products:
        return str(products[0].get("name") or "Elite 300")
    return "Elite 300"


def _first_direction_name() -> str:
    directions = repo.list_directions()
    if directions:
        return str(directions[0].get("name") or "⑤功能解说型")
    return "⑤功能解说型"


def _quick_product_name(value: str) -> str:
    raw = (value or "").strip()
    if not raw:
        return _first_product_name()
    p = repo.get_product(raw) or repo.get_product_by_name(raw)
    if p:
        return str(p.get("name") or raw)
    return raw


def _quick_direction_name(value: str) -> str:
    raw = (value or "").strip()
    if not raw:
        return _first_direction_name()
    d = repo.get_direction(raw) or repo.get_direction_by_short_code(raw)
    if d:
        return str(d.get("name") or raw)
    return raw


@app.get("/api/toc/locale")
async def toc_ui_locale(request: Request):
    """UI 语言：根据 IP / CDN 国家头 / 域名推断，前端可用手动切换覆盖。"""
    loc, source = detect_ui_locale(request)
    return {"locale": loc, "source": source}


@app.get("/api/toc/config")
async def toc_config(request: Request):
    payload = _toc_config()
    _toc_track(request, "config_viewed")
    return payload


@app.post("/api/toc/quick-generate/estimate")
async def toc_quick_generate_estimate(body: TocQuickEstimateRequest, request: Request):
    """To C 快速生成估算：优先走主站 getTaskCost，失败时返回降级区间。"""
    from src.platform.billing import billing_enabled, estimate_video_cost
    from src.platform.client import build_video_task_params

    settings = get_settings()
    estimate = {
        "currency": "credits",
        "estimated_credits": None,
        "range": [300, 650],
        "provider": (settings.video_provider or "seedance").lower(),
        "fallback": True,
    }
    token = _platform_token_for_video(request)
    if billing_enabled(settings) and token:
        model_name = (body.model_name or settings.platform_video_model or "happyhorse_1.0").strip()
        task_params = build_video_task_params(
            prompt=body.brief,
            model_name=model_name,
            duration=body.duration_sec,
            ratio=body.ratio,
            resolution=body.resolution,
            first_frame_url="",
        )
        try:
            cost = await estimate_video_cost(token, task_params)
            estimate.update(
                {
                    "estimated_credits": round(float(cost), 2),
                    "range": [round(float(cost), 2), round(float(cost), 2)],
                    "fallback": False,
                }
            )
        except Exception as exc:
            estimate["estimate_error"] = str(exc)
    _toc_track(
        request,
        "toc_quick_estimate",
        {"has_precise_estimate": not estimate["fallback"], "provider": estimate["provider"]},
    )
    return estimate


@app.get("/api/toc/intake/formats")
async def toc_intake_formats():
    """Copilot 可上传的参考素材格式（与前端 accept 对齐）。"""
    return intake_formats_public()


@app.post("/api/toc/intake/analyze")
async def toc_intake_analyze(
    request: Request,
    files: list[UploadFile] = File(default=[]),
    pdf: UploadFile | None = File(None),
    reference_video: UploadFile | None = File(None),
    reference_video_url: str = "",
    product_page_url: str = "",
    user_note: str = "",
    product_hint: str = "",
):
    """Copilot 参考素材：多格式文件 + 链接 → 结构化 brief。"""
    _ = access_context(request)
    settings = get_settings()
    if not (
        gemini_configured(settings)
        or (settings.llm_provider or "").lower() == "gemini"
        or (settings.llm_fallback_provider or "").lower() == "gemini"
    ):
        if not settings.nuwa_api_key and not settings.openai_api_key:
            raise HTTPException(
                400,
                "未配置 Gemini/Vertex 多模态能力，无法解析 PDF/视频/图片（请检查测试服 GEMINI 或 Vertex 凭据）",
            )

    attachments: list[tuple[str, bytes]] = []
    for upload in files:
        if not upload.filename:
            continue
        data = await upload.read()
        if not data:
            raise HTTPException(400, f"文件为空: {upload.filename}")
        attachments.append((upload.filename, data))

    if pdf and pdf.filename:
        data = await pdf.read()
        if not data:
            raise HTTPException(400, "PDF 文件为空")
        attachments.append((pdf.filename, data))

    if reference_video and reference_video.filename:
        data = await reference_video.read()
        if not data:
            raise HTTPException(400, "对标视频文件为空")
        attachments.append((reference_video.filename, data))

    url = (reference_video_url or "").strip() or extract_video_url(user_note)

    try:
        result = await analyze_intake_materials(
            settings,
            attachments=attachments,
            reference_video_url=url,
            product_page_url=product_page_url,
            user_note=user_note,
            product_hint=product_hint,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        msg = str(exc).strip() or exc.__class__.__name__
        raise HTTPException(400, f"素材解析失败: {msg}") from exc

    counts = (result.get("sources") or {}).get("counts") or {}
    _toc_track(
        request,
        "toc_intake_analyze",
        {
            "file_count": len(attachments),
            "has_url": bool(url),
            "has_product_page": bool((result.get("sources") or {}).get("product_page_url")),
            "counts": counts,
        },
    )
    return result


# ---------------------------------------------------------------------------
# Workflow Blueprint — 参考视频拆解 + 定制产线
# ---------------------------------------------------------------------------


@app.post("/api/workflows/reference/decompose")
async def workflow_decompose_reference(
    request: Request,
    reference_video: UploadFile = File(...),
    user_note: str = "",
    product_hint: str = "",
):
    """上传对标参考视频，返回结构化拆解（节奏/钩子/叙事/推荐时长）。"""
    _ = access_context(request)
    settings = get_settings()
    if not gemini_configured(settings) and not settings.nuwa_api_key:
        raise HTTPException(400, "未配置 Gemini/NUWA，无法拆解参考视频")

    url, data = await save_reference_video(reference_video)
    filename = reference_video.filename or "reference.mp4"
    try:
        result = await decompose_reference_video(
            settings,
            video_bytes=data,
            filename=filename,
            user_note=user_note,
            product_hint=product_hint,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"参考视频拆解失败: {exc}") from exc

    import json as _json

    repo.create_reference_decomposition(
        {
            "id": result["id"],
            "source_url": url,
            "source_filename": filename,
            "payload_json": _json.dumps(result["payload"], ensure_ascii=False),
            "created_at": result["created_at"],
        }
    )
    return {
        "decomposition_id": result["id"],
        "source_url": url,
        "payload": result["payload"],
    }


@app.post("/api/workflows/reference/learn-style")
async def workflow_learn_reference_style(
    request: Request,
    reference_videos: list[UploadFile] = File(default=[]),
    product_images: list[UploadFile] = File(default=[]),
    user_note: str = "",
    product_hint: str = "",
):
    """多条 TikTok 对标视频 + 产品实拍图 → UGC 风格画像（达人穿搭、粉末真相、CTA）。"""
    _ = access_context(request)
    settings = get_settings()
    if not gemini_configured(settings) and not settings.nuwa_api_key:
        raise HTTPException(400, "未配置 Gemini/NUWA")

    vids: list[tuple[str, bytes]] = []
    for upload in reference_videos:
        if not upload.filename:
            continue
        data = await upload.read()
        if data:
            vids.append((upload.filename, data))
    if not vids:
        raise HTTPException(400, "请至少上传 1 条参考视频")

    imgs: list[tuple[str, bytes]] = []
    for upload in product_images:
        if not upload.filename:
            continue
        data = await upload.read()
        if data:
            imgs.append((upload.filename, data))

    try:
        result = await learn_reference_style(
            settings,
            reference_videos=vids,
            product_images=imgs or None,
            user_note=user_note,
            product_hint=product_hint,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"风格学习失败: {exc}") from exc

    import json as _json

    repo.create_reference_decomposition(
        {
            "id": result["id"],
            "source_url": "",
            "source_filename": ",".join(result.get("source_filenames") or [])[:500],
            "payload_json": _json.dumps(result["payload"], ensure_ascii=False),
            "created_at": result["created_at"],
        }
    )
    return {
        "decomposition_id": result["id"],
        "source_filenames": result.get("source_filenames"),
        "product_image_count": result.get("product_image_count", 0),
        "payload": result["payload"],
    }


@app.post("/api/workflows/reference/seed-decomposition")
async def workflow_seed_decomposition(
    body: ReferenceDecompositionSeed, request: Request
):
    """测试服同步参考拆解（auth 关闭或管理员）。生产环境请用 decompose / learn-style。"""
    _ = require_admin(request)
    import json as _json

    decomp_id = (body.id or "").strip()
    if not decomp_id:
        raise HTTPException(400, "id 不能为空")
    existing = repo.get_reference_decomposition(decomp_id)
    if existing:
        return {"ok": True, "id": decomp_id, "skipped": "already exists"}
    payload_json = _json.dumps(body.payload or {}, ensure_ascii=False)
    repo.create_reference_decomposition(
        {
            "id": decomp_id,
            "source_url": body.source_url,
            "source_filename": body.source_filename,
            "payload_json": payload_json,
            "created_at": datetime.now(UTC).isoformat(),
        }
    )
    return {"ok": True, "id": decomp_id, "created": True}


@app.get("/api/workflows/reference/{decomposition_id}")
async def workflow_get_decomposition(decomposition_id: str, request: Request):
    _ = access_context(request)
    row = repo.get_reference_decomposition(decomposition_id)
    if not row:
        raise HTTPException(404, "参考拆解不存在")
    import json as _json

    return {
        "decomposition_id": row["id"],
        "source_url": row.get("source_url", ""),
        "source_filename": row.get("source_filename", ""),
        "payload": _json.loads(row.get("payload_json") or "{}"),
    }


@app.post("/api/workflows/blueprints/from-decomposition")
async def workflow_create_blueprint_from_decomp(
    body: WorkflowBlueprintFromDecomp, request: Request
):
    """从参考拆解 + 产品信息生成 Workflow Blueprint（draft）。"""
    _ = access_context(request)
    row = repo.get_reference_decomposition(body.decomposition_id)
    if not row:
        raise HTTPException(404, "参考拆解不存在")

    product_specs = ""
    selling_points = ""
    product_name = body.product_name
    if body.product_id:
        prod = repo.get_product(body.product_id)
        if prod:
            product_specs = prod.get("product_specs", "") or ""
            selling_points = prod.get("selling_points", "") or ""
            product_name = product_name or prod.get("name", "")

    try:
        bp = create_blueprint_from_decomposition(
            repo,
            decomposition_row={
                **row,
                "source_url": row.get("source_url", ""),
            },
            product_id=body.product_id,
            product_name=product_name,
            product_specs=product_specs,
            selling_points=selling_points,
            reference_source=row.get("source_url", ""),
            reference_mode=body.reference_mode,
            platform=body.platform,
            goal=body.goal,
            patch=body.patch or None,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    return {"workflow_id": bp.workflow_id, "blueprint": bp.model_dump(), "status": bp.status}


@app.get("/api/workflows/blueprints/{workflow_id}")
async def workflow_get_blueprint(workflow_id: str, request: Request):
    _ = access_context(request)
    bp = load_blueprint(repo, workflow_id)
    if not bp:
        raise HTTPException(404, "工作流蓝图不存在")
    return bp.model_dump()


@app.patch("/api/workflows/blueprints/{workflow_id}")
async def workflow_patch_blueprint(
    workflow_id: str, body: WorkflowBlueprintPatch, request: Request
):
    _ = access_context(request)
    bp = load_blueprint(repo, workflow_id)
    if not bp:
        raise HTTPException(404, "工作流蓝图不存在")
    if bp.status == "confirmed":
        raise HTTPException(400, "已确认的工作流请复制为新草稿后再修改")

    patch = body.model_dump(exclude_unset=True)
    merged = bp.model_dump()
    for key, val in patch.items():
        if isinstance(val, dict) and isinstance(merged.get(key), dict):
            merged[key] = {**merged[key], **val}
        elif val is not None and val != "":
            merged[key] = val
    if body.product_id:
        prod = repo.get_product(body.product_id)
        if prod:
            merged["difficulty"] = assess_product_difficulty(
                product_specs=prod.get("product_specs", "") or "",
                selling_points=prod.get("selling_points", "") or "",
            ).model_dump()
            merged["production"] = {
                **merged.get("production", {}),
                "use_first_frame": merged["difficulty"].get("recommended_first_frame", False),
                "first_frame_reason": merged["difficulty"].get("first_frame_reason", ""),
            }
    updated = WorkflowBlueprint.model_validate(merged)
    updated.workflow_id = workflow_id
    save_blueprint(repo, updated)
    return updated.model_dump()


@app.get("/api/workflows/blueprints/{workflow_id}/confirmation")
async def workflow_confirmation_sheet(workflow_id: str, request: Request):
    _ = access_context(request)
    try:
        return get_confirmation_sheet(repo, workflow_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.post("/api/workflows/blueprints/{workflow_id}/confirm")
async def workflow_confirm_blueprint(workflow_id: str, request: Request):
    """用户确认生产方案后，才允许带 workflow_id 创建批次/出片。"""
    _ = access_context(request)
    try:
        bp = confirm_blueprint(repo, workflow_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"workflow_id": workflow_id, "status": bp.status, "confirmed_at": bp.confirmed_at}


@app.get("/api/workflows/production-options")
async def workflow_production_options(
    request: Request,
    native_audio: bool = True,
):
    """产线可选项：字幕方案等（Hermes / 前端展示，patch Blueprint 时引用 id）。"""
    _ = access_context(request)
    from src.pipeline.production_mode import (
        production_audio_subtitle_matrix,
        production_subtitle_options,
    )

    return {
        "subtitle_modes": production_subtitle_options(native_audio=native_audio),
        "audio_subtitle_matrix": production_audio_subtitle_matrix(),
        "patch_hint": "patch_workflow_blueprint → production.subtitles / production.tts / production.seedance_native_audio",
    }


@app.get("/api/workflows/blueprints")
async def workflow_list_blueprints(request: Request, product_id: str = ""):
    _ = access_context(request)
    rows = repo.list_workflow_blueprints(product_id=product_id)
    out = []
    for row in rows:
        bp = WorkflowBlueprint.from_storage(row.get("payload_json"))
        if bp:
            out.append(
                {
                    "workflow_id": row["id"],
                    "product_id": row.get("product_id", ""),
                    "product_name": row.get("product_name", ""),
                    "status": row.get("status", ""),
                    "confirmed_at": row.get("confirmed_at", ""),
                    "updated_at": row.get("updated_at", ""),
                    "summary": {
                        "duration_sec": bp.video_spec.duration_sec,
                        "segment_strategy": bp.video_spec.segment_strategy,
                        "use_first_frame": bp.production.use_first_frame,
                    },
                }
            )
    return out


@app.post("/api/toc/quick-generate")
async def toc_quick_generate(
    body: TocQuickGenerateRequest, request: Request, background_tasks: BackgroundTasks
):
    """To C 语义化入口：一句话/URL => 自动跑通脚本、分镜、视频。"""
    ctx = access_context(request)
    settings = get_settings()
    if not llm_ready(settings):
        raise HTTPException(400, "未配置可用的 LLM API Key（GEMINI / NUWA / OPENAI）")

    product = _quick_product_name(body.product)
    direction = _quick_direction_name(body.direction)
    language = (body.language or settings.toc_default_language or "英语").strip()
    extra_instruction = body.brief.strip()
    if body.material_context.strip():
        extra_instruction = f"{extra_instruction}\n\n{body.material_context.strip()}"
    if body.source_url.strip():
        extra_instruction = f"{extra_instruction}\n\n产品参考URL: {body.source_url.strip()}"
    if body.reference_video_url.strip():
        extra_instruction = (
            f"{extra_instruction}\n\n对标参考视频: {body.reference_video_url.strip()}"
        )
    reviewer = default_creator(ctx, body.creator) or "自动审核"
    creator = default_creator(ctx, body.creator)

    try:
        batch_id = orch.prepare_batch(
            product=product,
            direction=direction,
            count=body.count,
            extra_instruction=extra_instruction,
            creator=creator,
            difficulty_level="低级",
            language=language,
            owner_user_id=ctx["owner_user_id"] or "",
            use_first_frame=body.use_first_frame,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    background_tasks.add_task(
        orch.run_full_autopilot,
        batch_id,
        product=product,
        direction=direction,
        count=body.count,
        extra_instruction=extra_instruction,
        difficulty_level="低级",
        account_id="",
        language=language,
        producer=creator,
        reviewer=reviewer,
        use_first_frame=body.use_first_frame,
        platform_token=_platform_token_for_video(request),
    )
    _toc_track(
        request,
        "toc_quick_generate_started",
        {
            "batch_id": batch_id,
            "product": product,
            "direction": direction,
            "count": body.count,
            "has_url": bool(body.source_url.strip()),
        },
    )
    return {
        "batch_id": batch_id,
        "queued": True,
        "autopilot": True,
        "next": {
            "batches": "/api/batches",
            "scripts": f"/api/scripts?batch_id={batch_id}",
            "videos": "/api/videos",
        },
    }


@app.get("/api/toc/projects")
async def toc_projects(request: Request, limit: int = 20):
    """To C 项目摘要：用于“最近项目”与工作区卡片列表。"""
    ctx = access_context(request)
    rows = repo.list_batches(owner_user_id=ctx["owner_user_id"], admin=ctx["admin"])
    result: list[dict[str, Any]] = []
    for b in rows[: max(1, min(limit, 50))]:
        scripts = repo.list_scripts(
            batch_id=b["id"],
            owner_user_id=ctx["owner_user_id"],
            admin=ctx["admin"],
        )
        prompt_done = 0
        video_done = 0
        for s in scripts:
            p = repo.get_prompt_by_script(s["id"])
            if p and p.get("review_status") == "已通过":
                prompt_done += 1
            v = repo.get_video_by_script(s["id"])
            if v and str(v.get("status") or "").lower() in {"done", "completed", "succeeded"}:
                video_done += 1
        result.append(
            {
                "batch_id": b["id"],
                "title": f"{b.get('product', '')} · {b.get('direction', '')}",
                "status": b.get("status", ""),
                "created_at": b.get("created_at", ""),
                "script_total": len(scripts),
                "prompt_passed": prompt_done,
                "video_done": video_done,
            }
        )
    _toc_track(request, "toc_projects_viewed", {"count": len(result)})
    return {"items": result}


@app.post("/api/toc/metrics/events")
async def toc_metrics_event(body: TocMetricEvent, request: Request):
    safe_props = {k: v for k, v in body.properties.items() if k not in {"token", "password", "email"}}
    _toc_track(request, body.event, safe_props)
    return {"ok": True}


@app.get("/api/toc/metrics/events")
async def toc_metrics_events(request: Request, limit: int = 100):
    _toc_track(request, "toc_metrics_debug_view", {"limit": limit})
    max_rows = max(1, min(limit, 500))
    return {"items": _toc_metrics_events[-max_rows:]}


@app.get("/api/toc/copilot-hints")
async def toc_copilot_hints():
    """Copilot @ 提示：产品与内容风格列表。"""
    products = repo.list_products()
    directions = repo.list_directions()
    return {
        "mentions": [
            {
                "type": "product",
                "token": "产品",
                "items": [
                    {"id": p["id"], "label": p["name"], "insert": f"@{p['name']}"}
                    for p in products
                    if p.get("name")
                ],
            },
            {
                "type": "style",
                "token": "风格",
                "items": [
                    {
                        "id": d["id"],
                        "label": d["name"],
                        "insert": f"@{d.get('name', '')}",
                        "short_code": d.get("short_code", ""),
                    }
                    for d in directions
                    if d.get("name")
                ],
            },
        ]
    }


@app.patch("/api/toc/scripts/{script_id}")
async def toc_patch_script(script_id: str, body: TocScriptPatch, request: Request):
    """To C：保存脚本 Hook / 风格等字段（不触发重跑）。"""
    ensure_script_access(script_id, request, repo)
    script = repo.get_script(script_id)
    if not script:
        raise HTTPException(404, "脚本不存在")
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    if not fields:
        raise HTTPException(400, "无更新字段")
    if "hook" in fields and not str(fields["hook"]).strip():
        raise HTTPException(400, "Hook 不能为空")
    repo.update_script(script_id, fields)
    _toc_track(request, "toc_script_patched", {"script_id": script_id, "fields": list(fields)})
    return {"ok": True, "script_id": script_id}


@app.post("/api/toc/scripts/{script_id}/branch")
async def toc_branch_script(
    script_id: str,
    body: TocBranchRequest,
    request: Request,
    background_tasks: BackgroundTasks,
):
    """To C 分支：从指定节点重跑，默认创建新版本保留父流水线。"""
    ensure_script_access(script_id, request, repo)
    script = repo.get_script(script_id)
    if not script:
        raise HTTPException(404, "脚本不存在")
    token = _platform_token_for_video(request)

    target_id = script_id
    if body.create_branch:
        target_id = orch.copy_script_branch(
            script_id,
            hook=body.hook,
            direction=body.direction,
            branch_node=body.node,
        )
    else:
        fields: dict[str, Any] = {}
        if body.hook is not None:
            fields["hook"] = body.hook
        if body.direction is not None:
            fields["direction"] = body.direction
        if fields:
            repo.update_script(script_id, fields)

    async def _run() -> None:
        try:
            await orch.toc_branch_pipeline(
                script_id,
                target_script_id=target_id,
                node=body.node,
                note=body.note,
                platform_token=token,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"[ToCBranch] failed script={script_id} target={target_id}: {exc}")

    background_tasks.add_task(_run)
    _toc_track(
        request,
        "toc_branch_queued",
        {
            "script_id": script_id,
            "target_script_id": target_id,
            "node": body.node,
            "create_branch": body.create_branch,
        },
    )
    return {
        "ok": True,
        "queued": True,
        "batch_id": script.get("batch_id"),
        "source_script_id": script_id,
        "target_script_id": target_id,
        "node": body.node,
        "create_branch": body.create_branch,
    }


@app.get("/api/products")
async def list_products():
    return [enrich_product(p) for p in repo.list_products()]


@app.get("/api/products/{product_id}")
async def get_product(product_id: str):
    p = repo.get_product(product_id)
    if not p:
        raise HTTPException(404, "产品不存在")
    return enrich_product(p)


@app.post("/api/products")
async def create_product(body: ProductCreate):
    urls = _normalize_product_image_urls(body.image_urls, body.image_url)
    _validate_product_images(urls)
    pid = str(uuid.uuid4())[:8]
    data = body.model_dump(exclude={"image_urls", "image_url", "product_specs_confirmed"})
    data.update(product_image_db_fields(urls))
    data["product_specs_confirmed"] = 1 if body.product_specs_confirmed else 0
    repo.create_product({"id": pid, **data})
    return {"id": pid}


@app.patch("/api/products/{product_id}")
async def update_product(product_id: str, body: ProductUpdate):
    existing = repo.get_product(product_id)
    if not existing:
        raise HTTPException(404, "产品不存在")
    raw = body.model_dump(exclude_unset=True)
    fields = dict(raw)
    if "product_specs_confirmed" in fields:
        fields["product_specs_confirmed"] = 1 if fields.pop("product_specs_confirmed") else 0
    if "image_urls" in raw or "image_url" in raw:
        urls = _normalize_product_image_urls(
            raw.get("image_urls"),
            raw.get("image_url"),
        )
        _validate_product_images(urls)
        old_urls = parse_product_image_urls(existing)
        if urls != old_urls:
            fields["product_specs_confirmed"] = 0
        fields.pop("image_urls", None)
        fields.pop("image_url", None)
        fields.update(product_image_db_fields(urls))
    if "product_specs" in fields and fields.get("product_specs") != existing.get("product_specs"):
        if "product_specs_confirmed" not in fields:
            fields["product_specs_confirmed"] = 0
    repo.update_product(product_id, fields)
    return {"ok": True}


@app.delete("/api/products/{product_id}")
async def delete_product(product_id: str):
    repo.delete_product(product_id)
    return {"ok": True}


@app.post("/api/products/analyze-images")
async def analyze_product_images_preview(body: ProductAnalyzeRequest):
    urls = _normalize_product_image_urls(body.image_urls)
    _validate_product_images(urls)
    try:
        result = await analyze_product_images(
            get_settings(),
            product_name=body.product_name,
            image_urls=urls,
            existing_specs=body.existing_specs,
            existing_selling_points=body.existing_selling_points,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, str(exc)) from exc
    return {
        "product_specs_draft": result.get("product_specs_text", ""),
        "selling_points_draft": result.get("selling_points_suggested", ""),
        "vision": result,
    }


@app.post("/api/products/{product_id}/analyze-images")
async def analyze_product_images_for_id(product_id: str):
    product = repo.get_product(product_id)
    if not product:
        raise HTTPException(404, "产品不存在")
    urls = parse_product_image_urls(product)
    _validate_product_images(urls)
    try:
        result = await analyze_product_images(
            get_settings(),
            product_name=product.get("name", ""),
            image_urls=urls,
            existing_specs=product.get("product_specs", ""),
            existing_selling_points=product.get("selling_points", ""),
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, str(exc)) from exc
    stamp = datetime.now(UTC).isoformat()
    try:
        repo.update_product(
            product_id,
            {
                "product_specs_draft": str(result.get("product_specs_text") or ""),
                "selling_points_draft": str(result.get("selling_points_suggested") or ""),
                "product_specs_confirmed": 0,
                "vision_analyzed_at": stamp,
            },
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"识别成功但保存草稿失败: {exc}") from exc
    return {
        "product_specs_draft": result.get("product_specs_text", ""),
        "selling_points_draft": result.get("selling_points_suggested", ""),
        "vision_analyzed_at": stamp,
        "vision": result,
    }


@app.post("/api/products/{product_id}/confirm-specs")
async def confirm_product_specs(product_id: str, body: ProductConfirmSpecsRequest):
    product = repo.get_product(product_id)
    if not product:
        raise HTTPException(404, "产品不存在")
    specs = body.product_specs.strip()
    if not specs:
        raise HTTPException(400, "产品外观说明不能为空")
    repo.update_product(
        product_id,
        {
            "product_specs": specs,
            "selling_points": body.selling_points.strip() or product.get("selling_points", ""),
            "product_specs_confirmed": 1,
            "product_specs_draft": specs,
        },
    )
    return {"ok": True}


@app.post("/api/uploads/product-image")
async def upload_product_image(file: UploadFile = File(...)):
    url = await save_product_image(file)
    return {"url": url}


@app.post("/api/uploads/product-images")
async def upload_product_images(files: list[UploadFile] = File(...)):
    if not files:
        raise HTTPException(400, "请选择图片")
    if len(files) > MAX_PRODUCT_IMAGES:
        raise HTTPException(400, f"单次最多上传 {MAX_PRODUCT_IMAGES} 张图片")
    total_bytes = 0
    for f in files:
        data = await f.read()
        total_bytes += len(data)
        await f.seek(0)
    if total_bytes > MAX_UPLOAD_REQUEST_BYTES:
        raise HTTPException(400, "本次上传总大小不能超过 64MB（Seedance 请求体限制）")
    urls = [await save_product_image(f) for f in files]
    return {"urls": urls}


@app.get("/api/directions")
async def list_directions():
    return repo.list_directions()


@app.get("/api/directions/{direction_id}")
async def get_direction(direction_id: str):
    d = repo.get_direction(direction_id)
    if not d:
        raise HTTPException(404, "方向不存在")
    return d


@app.post("/api/directions")
async def create_direction(body: DirectionCreate):
    did = str(uuid.uuid4())[:8]
    repo.create_direction({"id": did, **body.model_dump()})
    return {"id": did}


@app.patch("/api/directions/{direction_id}")
async def update_direction(direction_id: str, body: DirectionUpdate):
    repo.update_direction(direction_id, body.model_dump(exclude_unset=True))
    return {"ok": True}


@app.delete("/api/directions/{direction_id}")
async def delete_direction(direction_id: str):
    repo.delete_direction(direction_id)
    return {"ok": True}


@app.get("/api/accounts")
async def list_accounts():
    return repo.list_accounts()


@app.get("/api/accounts/{account_id}")
async def get_account(account_id: str):
    acc = repo.get_account(account_id)
    if not acc:
        raise HTTPException(404, "账号不存在")
    return acc


@app.post("/api/accounts")
async def create_account(body: AccountCreate):
    aid = str(uuid.uuid4())[:8]
    repo.create_account({"id": aid, **body.model_dump()})
    return {"id": aid}


@app.patch("/api/accounts/{account_id}")
async def update_account(account_id: str, body: AccountUpdate):
    repo.update_account(account_id, body.model_dump(exclude_unset=True))
    return {"ok": True}


@app.delete("/api/accounts/{account_id}")
async def delete_account(account_id: str):
    repo.delete_account(account_id)
    return {"ok": True}


@app.get("/api/config/export")
async def export_config(request: Request):
    require_admin(request)
    return export_fixed_config(repo)


@app.post("/api/config/import")
async def import_config(body: FixedConfigImportBody, request: Request):
    require_admin(request)
    try:
        stats = import_fixed_config(body.bundle, repo=repo)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True, "stats": stats}


@app.post("/api/config/import-csv/{kind}")
async def import_config_csv(kind: str, request: Request, file: UploadFile = File(...)):
    """kind: accounts | directions | products"""
    if kind not in ("accounts", "directions", "products"):
        raise HTTPException(400, "kind 须为 accounts、directions 或 products")
    raw = await file.read()
    if len(raw) > 5 * 1024 * 1024:
        raise HTTPException(400, "CSV 文件过大（最大 5MB）")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HTTPException(400, "请使用 UTF-8 编码的 CSV") from exc
    try:
        if kind == "accounts":
            stats = import_accounts_csv(text, repo=repo)
        elif kind == "directions":
            stats = import_directions_csv(text, repo=repo)
        else:
            stats = import_products_csv(text, repo=repo)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"CSV 解析失败: {exc}") from exc
    return {"ok": True, "kind": kind, "stats": stats}


@app.get("/api/difficulties")
async def list_difficulties():
    return repo.list_difficulty_levels()


@app.get("/api/production-board")
async def production_board(request: Request):
    ctx = access_context(request)
    return repo.list_production_board(
        owner_user_id=ctx["owner_user_id"],
        admin=ctx["admin"],
    )


def _board_download_assets(script_id: str, pkg: dict) -> list[dict]:
    filenames = pkg["download_filenames"]
    raw_segments = pkg.get("raw_segments") or {}
    video_url = pkg.get("video_url") or ""
    has_local_video = pkg.get("has_local_video", False)
    return [
        {
            "key": "zip",
            "label": "ZIP 素材包",
            "filename": filenames["zip"],
            "api": f"/api/scripts/{script_id}/download/zip",
            "available": True,
        },
        {"key": "script", "label": "视频脚本", "filename": filenames["script"], "available": True},
        {
            "key": "video",
            "label": "完整视频（含字幕/口播）",
            "filename": filenames["video"],
            "url": video_url,
            "available": bool(video_url),
        },
        {
            "key": "part_a",
            "label": "Part A 原片（无字幕）",
            "filename": filenames["part_a"],
            "url": raw_segments.get("part_a", ""),
            "available": bool(raw_segments.get("part_a")),
        },
        {
            "key": "part_b",
            "label": "Part B 原片（无字幕）",
            "filename": filenames["part_b"],
            "url": raw_segments.get("part_b", ""),
            "available": bool(raw_segments.get("part_b")),
        },
        {
            "key": "audio",
            "label": "口播音频",
            "filename": filenames["audio"],
            "api": f"/api/scripts/{script_id}/download/audio",
            "available": has_local_video,
        },
        {"key": "package", "label": "完整素材包 JSON", "filename": filenames["package"], "available": True},
    ]


def _load_board_package(script_id: str) -> dict | None:
    script = repo.get_script(script_id)
    if not script:
        return None
    prompt = repo.get_prompt_by_script(script_id)
    video = repo.get_video_by_script(script_id)
    account_name = ""
    if script.get("account_id"):
        acc = repo.get_account(script["account_id"])
        if acc:
            account_name = acc.get("display_name") or acc.get("username") or ""
    pkg = build_board_package(script, prompt, video, account_name)
    pkg["download_assets"] = _board_download_assets(script_id, pkg)
    return pkg


@app.get("/api/scripts/{script_id}/package")
async def script_package(script_id: str, request: Request):
    """脚本 + Prompt + 视频 打包信息，供看板浏览/下载。"""
    ensure_script_access(script_id, request, repo)
    pkg = _load_board_package(script_id)
    if not pkg:
        raise HTTPException(404, "脚本不存在")
    return pkg


@app.get("/api/scripts/{script_id}/download/zip")
async def download_script_zip(script_id: str, request: Request, background_tasks: BackgroundTasks):
    ensure_script_access(script_id, request, repo)
    pkg = _load_board_package(script_id)
    if not pkg:
        raise HTTPException(404, "脚本不存在")
    filename = pkg["download_filenames"]["zip"]
    try:
        zip_path = await build_delivery_zip(pkg)
    except RuntimeError as exc:
        raise HTTPException(500, str(exc)) from exc

    def _cleanup(p: Path) -> None:
        p.unlink(missing_ok=True)

    background_tasks.add_task(_cleanup, zip_path)
    return FileResponse(
        zip_path,
        media_type="application/zip",
        filename=filename,
    )


@app.get("/api/scripts/{script_id}/download/audio")
async def download_script_audio(script_id: str, request: Request, background_tasks: BackgroundTasks):
    ensure_script_access(script_id, request, repo)
    script = repo.get_script(script_id)
    if not script:
        raise HTTPException(404, "脚本不存在")
    video = repo.get_video_by_script(script_id)
    if not video or not video.get("video_url"):
        raise HTTPException(404, "暂无成片，无法导出口播音频")
    path = local_video_path_from_url(video["video_url"])
    if not path:
        raise HTTPException(400, "成片不在本地存储，无法导出音频")
    account_name = ""
    if script.get("account_id"):
        acc = repo.get_account(script["account_id"])
        if acc:
            account_name = acc.get("display_name") or acc.get("username") or ""
    filename = build_board_download_filenames(
        script.get("product", ""),
        script.get("direction", ""),
        account_name,
    )["audio"]
    try:
        wav_path = extract_audio_wav(path)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(500, str(exc)) from exc

    def _cleanup(p: Path) -> None:
        p.unlink(missing_ok=True)

    background_tasks.add_task(_cleanup, wav_path)
    return FileResponse(
        wav_path,
        media_type="audio/wav",
        filename=filename,
    )


@app.patch("/api/scripts/{script_id}/delivery")
async def update_script_delivery(script_id: str, body: ScriptDeliveryUpdate, request: Request):
    ensure_script_access(script_id, request, repo)
    script = repo.get_script(script_id)
    if not script:
        raise HTTPException(404, "脚本不存在")
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    if fields:
        repo.update_script(script_id, fields)
    return {"ok": True}


@app.get("/api/batches")
async def list_batches(request: Request):
    ctx = access_context(request)
    batches = repo.list_batches(owner_user_id=ctx["owner_user_id"], admin=ctx["admin"])
    for b in batches:
        scripts = repo.list_scripts(
            batch_id=b["id"],
            owner_user_id=ctx["owner_user_id"],
            admin=ctx["admin"],
        )
        b["script_total"] = len(scripts)
        b["script_pending"] = sum(1 for s in scripts if s["review_status"] == "待审核")
    return batches


@app.post("/api/batches")
async def create_batch(body: BatchCreate, request: Request, background_tasks: BackgroundTasks):
    ctx = access_context(request)
    settings = get_settings()
    if not llm_ready(settings):
        raise HTTPException(400, "未配置可用的 LLM API Key（GEMINI / NUWA / OPENAI）")
    try:
        batch_id = orch.prepare_batch(
            product=body.product,
            direction=body.direction,
            count=body.count,
            extra_instruction=body.extra_instruction,
            creator=default_creator(ctx, body.creator),
            difficulty_level=body.difficulty_level,
            language=body.language,
            owner_user_id=ctx["owner_user_id"] or "",
            use_first_frame=body.use_first_frame,
            workflow_id=body.workflow_id,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    background_tasks.add_task(
        orch.run_batch_scripts,
        batch_id,
        product=body.product,
        direction=body.direction,
        count=body.count,
        extra_instruction=body.extra_instruction,
        difficulty_level=body.difficulty_level,
        account_id=body.account_id,
        language=body.language,
        producer=body.producer,
        use_first_frame=body.use_first_frame,
    )
    return {"batch_id": batch_id, "queued": True}


@app.post("/api/batches/autopilot")
async def create_batch_autopilot(
    body: BatchCreate, request: Request, background_tasks: BackgroundTasks
):
    """新建批次并自动跑通：脚本 → Prompt → 视频（跳过人工审核）。"""
    ctx = access_context(request)
    settings = get_settings()
    if not llm_ready(settings):
        raise HTTPException(400, "未配置可用的 LLM API Key（GEMINI / NUWA / OPENAI）")
    reviewer = default_creator(ctx, body.creator) or "自动审核"
    try:
        batch_id = orch.prepare_batch(
            product=body.product,
            direction=body.direction,
            count=body.count,
            extra_instruction=body.extra_instruction,
            creator=default_creator(ctx, body.creator),
            difficulty_level=body.difficulty_level,
            language=body.language,
            owner_user_id=ctx["owner_user_id"] or "",
            use_first_frame=body.use_first_frame,
            workflow_id=body.workflow_id,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    background_tasks.add_task(
        orch.run_full_autopilot,
        batch_id,
        product=body.product,
        direction=body.direction,
        count=body.count,
        extra_instruction=body.extra_instruction,
        difficulty_level=body.difficulty_level,
        account_id=body.account_id,
        language=body.language,
        producer=body.producer,
        reviewer=reviewer,
        use_first_frame=body.use_first_frame,
        platform_token=_platform_token_for_video(request),
    )
    return {"batch_id": batch_id, "queued": True, "autopilot": True}


@app.post("/api/batches/{batch_id}/retry")
async def retry_batch(batch_id: str, request: Request, background_tasks: BackgroundTasks):
    ensure_batch_access(batch_id, request, repo)
    try:
        orch.begin_batch_retry(batch_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    background_tasks.add_task(orch.retry_batch_scripts, batch_id)
    return {"ok": True, "queued": True}


@app.delete("/api/batches/{batch_id}")
async def delete_batch(batch_id: str, request: Request):
    ensure_batch_access(batch_id, request, repo)
    try:
        orch.delete_failed_batch(batch_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True}


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return Response(status_code=204)


@app.get("/api/scripts")
async def list_scripts(
    request: Request,
    review_status: str | None = None,
    batch_id: str | None = None,
):
    ctx = access_context(request)
    if batch_id:
        ensure_batch_access(batch_id, request, repo)
    scripts = repo.list_scripts(
        review_status=review_status,
        batch_id=batch_id,
        owner_user_id=ctx["owner_user_id"],
        admin=ctx["admin"],
    )
    for s in scripts:
        s["account_name"] = account_display_name(s.get("account_id", ""))
    return scripts


@app.get("/api/scripts/{script_id}")
async def get_script(script_id: str, request: Request):
    script = ensure_script_access(script_id, request, repo)
    script["account_name"] = account_display_name(script.get("account_id", ""))
    return script


def _api_error(exc: Exception, action: str) -> HTTPException:
    msg = str(exc)
    if "429" in msg or "限流" in msg:
        return HTTPException(429, f"AI 接口请求过于频繁或配额不足：{msg}")
    if "UNIQUE constraint" in msg:
        return HTTPException(409, "该条已审核处理过，请刷新页面查看状态")
    return HTTPException(502, f"{action}失败：{msg}")


@app.post("/api/scripts/{script_id}/review")
async def review_script(
    script_id: str, body: ScriptReview, request: Request, background_tasks: BackgroundTasks
):
    ensure_script_access(script_id, request, repo)
    try:
        orch.begin_script_review(
            script_id, status=body.status, note=body.note, reviewer=body.reviewer
        )
    except ValueError as e:
        raise HTTPException(404, str(e)) from e
    background_tasks.add_task(
        orch.complete_script_review,
        script_id,
        status=body.status,
        note=body.note,
        reviewer=body.reviewer,
    )
    return {"ok": True, "queued": True}


@app.get("/api/prompts")
async def list_prompts(request: Request, review_status: str | None = None):
    ctx = access_context(request)
    prompts = repo.list_prompts(
        review_status=review_status,
        owner_user_id=ctx["owner_user_id"],
        admin=ctx["admin"],
    )
    for p in prompts:
        script = repo.get_script(p["script_id"])
        if script:
            enrich_from_script(p, script)
    return prompts


@app.get("/api/prompts/{prompt_id}")
async def get_prompt(prompt_id: str, request: Request):
    prompt = ensure_prompt_access(prompt_id, request, repo)
    script = repo.get_script(prompt["script_id"])
    prompt["script"] = script
    return prompt


@app.post("/api/prompts/{prompt_id}/review")
async def review_prompt(
    prompt_id: str, body: PromptReview, request: Request, background_tasks: BackgroundTasks
):
    ensure_prompt_access(prompt_id, request, repo)
    try:
        orch.begin_prompt_review(prompt_id, status=body.status, note=body.note)
    except ValueError as e:
        raise HTTPException(404, str(e)) from e
    background_tasks.add_task(
        orch.complete_prompt_review,
        prompt_id,
        status=body.status,
        note=body.note,
        platform_token=_platform_token_for_video(request),
    )
    return {"ok": True, "queued": True}


@app.get("/api/videos")
async def list_videos(request: Request):
    ctx = access_context(request)
    videos = repo.list_videos(
        owner_user_id=ctx["owner_user_id"],
        admin=ctx["admin"],
    )
    for v in videos:
        script = repo.get_script(v["script_id"])
        if script:
            enrich_from_script(v, script)
    return videos


@app.patch("/api/videos/{video_id}")
async def update_video(video_id: str, body: VideoUpdate, request: Request):
    ensure_video_access(video_id, request, repo)
    video = repo.get_video(video_id)
    if not video:
        raise HTTPException(404, "视频不存在")
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    if fields:
        repo.update_video(video_id, fields)
    return {"ok": True}


@app.post("/api/videos/{video_id}/retry")
async def retry_video(video_id: str, request: Request, background_tasks: BackgroundTasks):
    ensure_video_access(video_id, request, repo)
    try:
        orch.begin_video_retry(video_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    background_tasks.add_task(
        orch.complete_video_retry, video_id, _platform_token_for_video(request)
    )
    return {"ok": True, "queued": True}


@app.post("/api/videos/{video_id}/recover")
async def recover_video(video_id: str, request: Request, background_tasks: BackgroundTasks):
    video = ensure_video_access(video_id, request, repo)
    if video.get("output_status") != "生成中":
        raise HTTPException(400, "仅可恢复状态为「生成中」且可能中断的任务")
    background_tasks.add_task(orch.recover_stuck_video, video_id)
    return {"ok": True, "queued": True}


@app.post("/api/videos/{video_id}/segments/{segment}/regenerate")
async def regenerate_video_segment(
    video_id: str, segment: str, request: Request, background_tasks: BackgroundTasks
):
    ensure_video_access(video_id, request, repo)
    try:
        orch.begin_segment_regenerate(video_id, segment)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    background_tasks.add_task(
        orch.complete_segment_regenerate,
        video_id,
        segment,
        _platform_token_for_video(request),
    )
    return {"ok": True, "queued": True, "segment": segment}


@app.delete("/api/videos/{video_id}")
async def delete_video(video_id: str, request: Request):
    ensure_video_access(video_id, request, repo)
    try:
        orch.delete_video_record(video_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True}


@app.post("/api/videos/{video_id}/burn-subtitles")
async def burn_video_subtitles(video_id: str, request: Request, background_tasks: BackgroundTasks):
    video = ensure_video_access(video_id, request, repo)
    if video.get("output_status") == "生成中":
        raise HTTPException(400, "视频生成中，请稍候")

    async def _run() -> None:
        try:
            await orch.burn_subtitles_for_video(video_id)
        except Exception as exc:  # noqa: BLE001
            repo.update_video(
                video_id,
                {"note": f"{video.get('note', '')} · 字幕烧录失败: {exc}".strip(" ·")},
            )

    background_tasks.add_task(_run)
    return {"ok": True, "queued": True}


@app.get("/api/canvas/state")
async def canvas_state(request: Request, batch_id: str = "", script_id: str = ""):
    """Workflow canvas snapshot for Hermes MCP / embed preview (read-only)."""
    state = build_canvas_state(
        repo,
        batch_id=batch_id.strip(),
        script_id=script_id.strip(),
    )
    settings = get_settings()
    host = (request.headers.get("host") or "").strip()
    if host:
        scheme = (request.headers.get("x-forwarded-proto") or request.url.scheme or "https").split(",")[0].strip()
        base = f"{scheme}://{host}".rstrip("/")
    else:
        base = (settings.public_base_url or "").rstrip("/") or f"http://127.0.0.1:{settings.webhook_port}"
    bid = state.get("batch_id") or ""
    q = f"?batch_id={bid}" if bid else ""
    state["preview_url"] = f"{base}/hermes/canvas{q}"
    return state


@app.get("/api/canvas/svg")
async def canvas_svg(batch_id: str = "", script_id: str = ""):
    state = build_canvas_state(
        repo,
        batch_id=batch_id.strip(),
        script_id=script_id.strip(),
    )
    svg = canvas_to_svg(state)
    return Response(content=svg, media_type="image/svg+xml; charset=utf-8")


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/.well-known/skills/index.json", include_in_schema=False)
async def hermes_skills_index():
    """Hermes 远程 Skill 安装清单（与 creative.vidau.info 同协议）。"""
    return build_skills_index()


@app.get("/.well-known/skills/{skill_name}/SKILL.md", include_in_schema=False)
async def hermes_skill_file(skill_name: str):
    path = skill_md_path(skill_name)
    if not path:
        raise HTTPException(404, f"Skill not found: {skill_name}")
    return FileResponse(path, media_type="text/markdown; charset=utf-8")


_, _adflow_mcp_http_app = init_mcp_http()
app.mount("/mcp", _adflow_mcp_http_app)


ensure_upload_dirs()
if UPLOADS_DIR.exists():
    app.mount("/uploads", StaticFiles(directory=UPLOADS_DIR), name="uploads")


def _frontend_asset_version() -> str:
    stamps: list[int] = []
    for name in ("app.js", "i18n.js", "flow.css"):
        path = FRONTEND_DIR / name
        if path.is_file():
            stamps.append(int(path.stat().st_mtime))
    return str(max(stamps)) if stamps else "0"


if FRONTEND_DIR.exists():

    def _render_frontend_html(filename: str, scripts: list[str]) -> Response:
        html = (FRONTEND_DIR / filename).read_text(encoding="utf-8")
        version = _frontend_asset_version()
        html = html.replace(
            'href="/assets/styles.css"',
            f'href="/assets/styles.css?v={version}"',
        )
        html = html.replace(
            'href="/assets/flow.css"',
            f'href="/assets/flow.css?v={version}"',
        )
        for script in scripts:
            html = html.replace(
                f'src="/assets/{script}"',
                f'src="/assets/{script}?v={version}"',
            )
        return Response(
            content=html,
            media_type="text/html; charset=utf-8",
            headers=_NO_CACHE_HEADERS,
        )

    @app.get("/assets/app.js")
    async def frontend_app_js():
        return FileResponse(
            FRONTEND_DIR / "app.js",
            media_type="application/javascript",
            headers=_NO_CACHE_HEADERS,
        )

    @app.get("/assets/i18n.js")
    async def frontend_i18n_js():
        return FileResponse(
            FRONTEND_DIR / "i18n.js",
            media_type="application/javascript",
            headers=_NO_CACHE_HEADERS,
        )

    @app.get("/assets/flow.css")
    async def frontend_flow_css():
        return FileResponse(
            FRONTEND_DIR / "flow.css",
            media_type="text/css",
            headers=_NO_CACHE_HEADERS,
        )

    @app.get("/assets/sso.js")
    async def frontend_sso_js():
        return FileResponse(
            FRONTEND_DIR / "sso.js",
            media_type="application/javascript",
            headers=_NO_CACHE_HEADERS,
        )

    @app.get("/assets/pro.js")
    async def frontend_pro_js():
        return FileResponse(
            FRONTEND_DIR / "pro.js",
            media_type="application/javascript",
            headers=_NO_CACHE_HEADERS,
        )

    @app.get("/assets/styles.css")
    async def frontend_styles_css():
        return FileResponse(
            FRONTEND_DIR / "styles.css",
            media_type="text/css",
            headers=_NO_CACHE_HEADERS,
        )

    app.mount("/assets", StaticFiles(directory=FRONTEND_DIR), name="assets")

    @app.get("/login")
    async def login_page():
        return _render_frontend_html("login.html", ["sso.js"])

    @app.get("/hermes/canvas")
    async def hermes_canvas_page():
        path = FRONTEND_DIR / "hermes_canvas.html"
        if not path.is_file():
            raise HTTPException(404, "hermes_canvas.html not found")
        return Response(
            content=path.read_text(encoding="utf-8"),
            media_type="text/html; charset=utf-8",
            headers=_NO_CACHE_HEADERS,
        )

    @app.get("/")
    async def index():
        return _render_frontend_html("index.html", ["i18n.js", "sso.js", "app.js"])

    @app.get("/pro")
    async def pro_panel():
        return _render_frontend_html("pro.html", ["sso.js", "pro.js"])

    @app.get("/toc")
    async def toc_redirect():
        return RedirectResponse(url="/", status_code=302)
