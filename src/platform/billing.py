"""出片积分 — Agent 扣币 / 退币。

流程：getTaskCost 取价 → POST /inner/agent/coin/deduct（幂等 biz_no）→ 出片；
失败时 POST /inner/agent/coin/refund 全额退回。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.config import Settings, get_settings
from src.platform.client import (
    AI_VIDEO_APP_ID,
    AgentCoinResult,
    PlatformError,
    build_video_task_params,
    get_platform_client,
)


class InsufficientCreditsError(Exception):
    def __init__(self, coin: float, needed: float):
        super().__init__(f"积分不足：余额 {coin}，需 {needed}")
        self.coin = coin
        self.needed = needed


@dataclass
class VideoCharge:
    """单次分段出片的扣币记录（可写入 segment_urls_json.charges）。"""

    biz_no: str
    order_sn: str
    coin_number: float
    balance: float
    user_id: str = ""


def billing_enabled(settings: Settings | None = None) -> bool:
    settings = settings or get_settings()
    if (settings.aigc_billing_mode or "none").lower() == "platform":
        return True
    return (settings.video_provider or "").lower() == "platform"


async def estimate_video_cost(
    token: str,
    task_params: dict[str, Any],
    *,
    app_id: str = AI_VIDEO_APP_ID,
) -> float:
    """POST /taskV2/getTaskCost — 返回本次任务所需 coin。"""
    cost_info = await get_platform_client().get_video_task_cost(
        token, task_params, app_id=app_id
    )
    cost = float(cost_info.get("cost") or 0)
    if cost <= 0:
        raise PlatformError("主站 getTaskCost 未返回有效 cost")
    return cost


async def charge_for_video_task(
    token: str,
    *,
    biz_no: str,
    task_params: dict[str, Any] | None = None,
    prompt: str = "",
    model_name: str = "happyhorse_1.0",
    duration_sec: int = 15,
    ratio: str = "9:16",
    resolution: str = "1080p",
    first_frame_url: str = "",
    remark: str = "",
    app_id: str = AI_VIDEO_APP_ID,
    settings: Settings | None = None,
) -> VideoCharge | None:
    """出片前扣币：getTaskCost 取价 + agent deduct（biz_no 幂等）。"""
    settings = settings or get_settings()
    if not billing_enabled(settings):
        return None
    if not token:
        raise PlatformError("出片扣币缺少用户 token")
    if not biz_no.strip():
        raise PlatformError("出片扣币缺少 biz_no")
    if not (settings.agent_coin_api_key or "").strip():
        raise PlatformError("未配置 AGENT_COIN_API_KEY")

    client = get_platform_client()
    profile = await client.get_user_info(token)
    params = task_params or build_video_task_params(
        prompt=prompt,
        model_name=model_name,
        duration=duration_sec,
        ratio=ratio,
        resolution=resolution,
        first_frame_url=first_frame_url,
    )
    coin_number = await estimate_video_cost(token, params, app_id=app_id)

    try:
        result = await client.deduct_agent_coin(
            profile.user_id,
            coin_number,
            biz_no.strip(),
            remark=remark or f"workflow video {biz_no}",
        )
    except PlatformError as exc:
        if exc.code == -100:
            balance = (await client.get_user_info(token)).coin
            raise InsufficientCreditsError(balance, coin_number) from exc
        raise

    return VideoCharge(
        biz_no=biz_no.strip(),
        order_sn=result.order_sn,
        coin_number=result.coin_number or coin_number,
        balance=result.balance,
        user_id=profile.user_id,
    )


async def refund_video_charge(
    *,
    biz_no: str = "",
    order_sn: str = "",
    settings: Settings | None = None,
) -> AgentCoinResult | None:
    """出片失败退币（幂等）。"""
    settings = settings or get_settings()
    if not billing_enabled(settings):
        return None
    if not biz_no.strip() and not order_sn.strip():
        return None
    if not (settings.agent_coin_api_key or "").strip():
        raise PlatformError("未配置 AGENT_COIN_API_KEY")
    return await get_platform_client().refund_agent_coin(
        biz_no=biz_no,
        order_sn=order_sn,
    )


async def precheck_balance(
    token: str, *, needed: float = 1.0, settings: Settings | None = None
) -> float | None:
    """简单余额预检（仅看 coin 数值）。"""
    settings = settings or get_settings()
    if not billing_enabled(settings):
        return None
    if not token:
        raise PlatformError("出片余额预检缺少用户 token")
    coin = await get_platform_client().get_coin(token)
    if coin < needed:
        raise InsufficientCreditsError(coin, needed)
    return coin
