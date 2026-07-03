from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent
PROMPTS_DIR = ROOT / "config" / "prompts"
INTERNAL_ENV = ROOT / "config" / "internal.env"
VERTEX_ENV = ROOT / "config" / "env.vertex.snippet"
SEEDANCE_ENV = ROOT / "config" / "env.seedance.snippet"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        # internal.env 仅本地；snippet 随仓库部署；.env 最后覆盖
        env_file=(INTERNAL_ENV, VERTEX_ENV, SEEDANCE_ENV, ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # LLM：gemini | nuwa | openai；失败时可自动切 llm_fallback_provider
    llm_provider: str = "gemini"
    llm_fallback_provider: str = "nuwa"

    gemini_api_key: str = ""
    gemini_api_base: str = "https://generativelanguage.googleapis.com/v1beta"
    gemini_text_model: str = "gemini-2.0-flash"
    gemini_use_vertex: bool = False
    gemini_vertex_project: str = ""
    gemini_vertex_location: str = "us-central1"
    gemini_vertex_credentials: str = ""

    nuwa_api_key: str = ""
    nuwa_api_base: str = "https://api.nuwaapi.com/v1"
    nuwa_model: str = "gpt-4o-mini"
    nuwa_vision_model: str = ""  # 空则按 NUWA_VISION_MODEL_FALLBACKS 依次尝试

    openai_api_key: str = ""
    openai_model: str = "gpt-4.1-mini"

    llm_request_interval_sec: float = 0.0
    llm_max_concurrency: int = 3
    llm_retry_attempts: int = 2  # 主/备通道失败后额外重试次数（应对偶发超时/限流）
    llm_retry_backoff_sec: float = 2.0  # 重试退避基数（秒），按第几次线性放大

    # 首帧交互图（Nano Banana 2/Pro）：复杂交互产品先出图，再作 Seedance 首帧
    first_frame_model: str = "gemini-3-pro-image"  # gemini-3-pro-image | gemini-3.1-flash-image
    first_frame_image_size: str = "2K"  # 512 | 1K | 2K | 4K
    first_frame_aspect_ratio: str = "9:16"

    # 视频：seedance（火山方舟）| platform（主站 aiVideo 扣积分）| openai 占位
    video_provider: str = "seedance"

    seedance_api_key: str = ""
    seedance_api_base: str = "https://ark.cn-beijing.volces.com"
    seedance_model: str = "ep-20260513151304-mtzpn"
    seedance_model_fast: str = "ep-20260513151335-tc8qj"
    seedance_use_fast: bool = False
    seedance_poll_interval_sec: float = 3.0

    # 主站 AI Video（video_provider=platform 或 aigc_billing_mode=platform 时）
    platform_video_model: str = "happyhorse_1.0"
    platform_video_resolution: str = "1080p"
    platform_video_poll_interval_sec: float = 5.0

    video_api_key: str = ""
    video_api_base: str = "https://api.openai.com/v1"
    video_model: str = "sora"

    webhook_host: str = "127.0.0.1"
    webhook_port: int = 8787

    # 对外访问域名（Nginx 反代后填写，供前端/文档展示）
    public_base_url: str = "https://adflow.vidau.ai"
    app_domain: str = "adflow.vidau.ai"

    # 字幕：口播音频强制对齐（faster-whisper）
    subtitle_align_enabled: bool = True
    subtitle_whisper_model: str = "base.en"
    subtitle_whisper_device: str = "cpu"
    subtitle_whisper_compute_type: str = "int8"
    subtitle_whisper_hf_endpoint: str = "https://hf-mirror.com"
    subtitle_whisper_download_root: str = "data/models/whisper"
    subtitle_align_provider: str = "auto"  # auto | local | openai

    # TTS 后期口播（Edge TTS 替换 Seedance 音轨 + 时间戳烧字幕）
    tts_post_enabled: bool = False
    tts_provider: str = "edge"  # edge | elevenlabs（预留）
    tts_voice: str = ""  # 空则按 voice_profile 自动选
    tts_mute_seedance_audio: bool = False  # False = Seedance 原生配音（推荐 TikTok UGC）
    tts_rate: str = "+0%"  # Edge TTS 语速，如 +5% / -10%
    tts_segment_gap_sec: float = 0.2  # 句间停顿（秒）
    tts_pause_gap_sec: float = 0.2  # 词间停顿超过此值则另起一屏字幕
    tts_fit_to_video_sec: float = 15.0  # 目标成片时长；口播更长时片尾定格延长
    tts_extend_video: bool = True  # 口播未播完时延长视频（末帧定格），而非硬切
    tts_max_speedup: float = 1.1  # 仅略微超时（≤10%）时整体微加速，否则延长片长

    # 默认成片规格（无 Workflow Blueprint 时）
    video_default_duration_sec: int = 15
    video_segment_strategy: str = "single"  # single | dual
    seedance_ugc_style: bool = True  # TikTok 爆款 UGC 快节奏（非慢镜头产品片）
    seedance_asset_public_base_url: str = ""  # 参考视频公网前缀，如 https://cdn.example.com

    # 数据库（默认 SQLite，路径相对项目根目录）
    database_path: str = "data/workflow.db"
    # 设置后切换到 PostgreSQL，例如 postgresql://vidau:vidau@localhost:5433/vidau_flow
    # 留空则继续使用上面的 SQLite。
    database_url: str = ""

    # 登录鉴权（生产建议开启）
    auth_enabled: bool = False
    secret_key: str = "change-me-in-production"
    auth_cookie_secure: bool = False  # HTTPS 部署时设为 true
    admin_email: str = ""
    admin_password: str = ""
    admin_display_name: str = "管理员"

    # 鉴权模式：local（本地 users 表 + 密码登录）| platform（VidAU 主站 Token + getUserInfo）
    auth_mode: str = "local"
    # 主站对接（platform 模式 / 积分 / 上传 / 扣费）
    platform_api_url: str = "https://app-api.vidau.info/api"
    # 可选服务端鉴权头 X-Service-Auth（S2S），留空则不发送
    service_auth_secret: str = ""
    # token → userId 内存缓存 TTL（毫秒）
    auth_user_cache_ttl_ms: int = 60000
    # 开发兜底：主站不可达时从 JWT payload 解析 userId（仅限本地冒烟，生产请关）
    auth_dev_fallback: bool = False
    # 主站 Cookie / 开发 token Cookie 名（与 editor/agent 对齐）
    platform_token_cookie: str = "VidAu-Token"
    platform_dev_token_cookie: str = "VidAu-Agent-Dev-Token"
    # VidAU SSO（auth_mode=platform 时统一登录）
    sso_app_id: str = ""
    sso_env: str = ""  # production | development | 留空则按 APP_DOMAIN（.vidau.info→测试，.vidau.ai→正式）
    sso_base_url: str = ""  # 覆盖默认 sso.vidau.ai / sso.vidau.info
    # AIGC 计费：none（不扣）| platform（Agent 扣币/退币 + 主站出片）
    aigc_billing_mode: str = "none"
    # Agent 扣退币 inner API（POST /inner/agent/coin/deduct|refund）的 api-key
    agent_coin_api_key: str = ""
    # Agent 套餐购买（跳转主站 agent-price 页）
    agent_code: str = "vidau_flow"
    agent_purchase_base_url: str = "https://www.vidau.ai/agent-price"
    # True：仅认 SSO callback 写入的 Flow session Cookie，不因浏览器 VidAu-Token 静默登录
    auth_flow_session_only: bool = True
    # 首页快速生成默认语言
    toc_default_language: str = "英语"
    # To C 事件埋点开关（仅日志，不含用户隐私明文字段）
    toc_metrics_enabled: bool = True


def _non_empty_env_values(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    try:
        from dotenv import dotenv_values
    except ImportError:
        return {}
    return {
        k: str(v).strip()
        for k, v in dotenv_values(path).items()
        if v is not None and str(v).strip() != ""
    }


def _field_name_for_env_key(env_key: str) -> str | None:
    key = env_key.upper()
    for name in Settings.model_fields:
        if name.upper() == key:
            return name
    return None


@lru_cache
def get_settings() -> Settings:
    # internal.env 为底；.env / 系统环境变量仅非空值覆盖（空行不算配置，避免盖掉内置 key）
    merged = _non_empty_env_values(INTERNAL_ENV)
    merged.update(_non_empty_env_values(ROOT / ".env"))
    import os

    for env_key, val in os.environ.items():
        if val and str(val).strip():
            merged[env_key] = str(val).strip()

    kwargs: dict[str, object] = {}
    for env_key, val in merged.items():
        field = _field_name_for_env_key(env_key)
        if field:
            kwargs[field] = val
    return Settings(**kwargs) if kwargs else Settings()


def load_prompt(name: str) -> str:
    path = PROMPTS_DIR / f"{name}.txt"
    return path.read_text(encoding="utf-8")
