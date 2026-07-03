"""VidAU 主站 API 客户端 — 对齐 editor 主站 axios 调用。

已联调确认（app-api.vidau.info，2026-06）：
- POST /v1/video/push          — 提交 AI 视频（body 为扁平 task params）
- POST /v1/video/queryTasks    — 轮询，body: {"taskId": "<parentTaskId>"}
- POST /taskV2/getTaskCost     — 预估费用，body: {"app_id":"119","task_params":{...}}
- POST /inner/agent/coin/deduct — Agent 扣币（api-key，幂等 biz_no）
- POST /inner/agent/coin/refund — Agent 退币（按 biz_no 或 order_sn）

出片计费：getTaskCost 取价 → agent deduct → push；失败时 agent refund。
请求头：Authorization / X-Token / token / lang（与 agent/editor 一致）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from src.config import Settings, get_settings

# 主站 AI Video 应用 ID（非 veo3）；来自 editor useCost 逻辑
AI_VIDEO_APP_ID = "119"

# 主站业务 envelope 中视为成功的 code
_OK_CODES = {0, 100, 200}


class PlatformError(Exception):
    """主站调用失败（网络错误或业务 code 非成功）。"""

    def __init__(self, message: str, *, code: int | None = None, status: int | None = None):
        super().__init__(message)
        self.code = code
        self.status = status


@dataclass
class UserProfile:
    user_id: str
    coin: float = 0.0
    nickname: str = ""
    avatar: str = ""
    email: str = ""
    raw: dict[str, Any] | None = None


@dataclass
class AgentCoinResult:
    """Agent 扣/退币接口 data 字段。"""

    order_sn: str
    coin_number: float = 0.0
    balance: float = 0.0
    user_id: int | None = None
    refund_coin: float = 0.0


@dataclass
class VideoTaskSnapshot:
    """parse_video_task 解析后的轮询快照。"""

    task_id: str
    task_status: int | None = None
    item_status: int | None = None
    progress: int = 0
    video_url: str = ""
    thumb_url: str = ""
    error: str = ""
    done: bool = False
    raw: dict[str, Any] | None = None


def _build_headers(token: str, settings: Settings) -> dict[str, str]:
    headers = {
        "Authorization": token,
        "X-Token": token,
        "token": token,
        "lang": "en",
        "Content-Type": "application/json",
    }
    secret = (settings.service_auth_secret or "").strip()
    if secret:
        headers["X-Service-Auth"] = secret
    return headers


def _extract_user_id(data: dict[str, Any]) -> str:
    for key in ("userId", "user_id", "sub", "id"):
        val = data.get(key)
        if val is not None and str(val).strip():
            return str(val).strip()
    return ""


def build_video_task_params(
    *,
    prompt: str,
    model_name: str = "happyhorse_1.0",
    task_type: str = "T2V",
    ratio: str = "9:16",
    resolution: str = "1080p",
    duration: int = 15,
    quantity: int = 1,
    generate_audio: bool = True,
    seed: int = -1,
    first_frame_url: str = "",
    last_frame_url: str = "",
    reference_urls: list[str] | None = None,
    camera_fixed: bool = False,
) -> dict[str, Any]:
    """构造 POST /v1/video/push 请求体（与 editor home AI Video 一致）。"""
    body: dict[str, Any] = {
        "prompt": prompt,
        "ratio": ratio,
        "resolution": (resolution or "1080p").lower(),
        "duration": int(duration),
        "quantity": int(quantity),
        "modelName": model_name,
        "generateAudio": bool(generate_audio),
        "seed": seed,
        "imageUrl": "",
        "startImageUrl": "",
        "imageUrlList": [],
        "taskType": task_type,
    }
    if first_frame_url:
        body["startImageUrl"] = {"fileUrl": first_frame_url, "source": 0}
        body["taskType"] = "I2V"
        if last_frame_url:
            body["lastImageUrl"] = {"fileUrl": last_frame_url, "source": 0}
    elif reference_urls:
        body["imageUrlList"] = [{"fileUrl": u, "source": 0} for u in reference_urls if u]
        body["taskType"] = "I2V"
    if camera_fixed:
        body["cameraFixed"] = True
    return body


def parse_video_task(payload: dict[str, Any]) -> VideoTaskSnapshot:
    """解析 POST /v1/video/queryTasks 响应。"""
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    if not isinstance(data, dict):
        data = {}
    items = data.get("list") or []
    first = items[0] if items else {}
    video_url = str(first.get("filePath") or first.get("file_url") or "")
    item_status = first.get("status")
    progress = int(first.get("progress") or 0)
    error = str(first.get("errorText") or first.get("error_text") or "")
    # status/filePath 取值来自联调；完成态一般为 filePath 非空或 status 进入终态
    done = bool(video_url) or item_status in (2, 3, 4, "2", "3", "4", "success", "completed")
    return VideoTaskSnapshot(
        task_id=str(data.get("taskId") or data.get("task_id") or ""),
        task_status=data.get("taskStatus"),
        item_status=item_status if isinstance(item_status, int) else None,
        progress=progress,
        video_url=video_url,
        thumb_url=str(first.get("thumbPath") or first.get("thumb_path") or ""),
        error=error,
        done=done,
        raw=data,
    )


class PlatformClient:
    """主站 API 客户端；每次按用户 token 构造请求头。"""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()

    @property
    def base_url(self) -> str:
        return (self.settings.platform_api_url or "").rstrip("/")

    async def _request(
        self,
        method: str,
        path: str,
        token: str,
        *,
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        timeout: float = 60.0,
    ) -> dict[str, Any]:
        if not self.base_url:
            raise PlatformError("未配置 PLATFORM_API_URL")
        url = f"{self.base_url}/{path.lstrip('/')}"
        headers = _build_headers(token, self.settings)
        try:
            async with httpx.AsyncClient(timeout=timeout) as cli:
                resp = await cli.request(
                    method, url, headers=headers, json=json_body, params=params
                )
        except httpx.HTTPError as exc:
            raise PlatformError(f"主站请求失败: {exc}") from exc
        if resp.status_code >= 500:
            raise PlatformError(f"主站 {resp.status_code}", status=resp.status_code)
        try:
            payload = resp.json()
        except ValueError as exc:
            raise PlatformError("主站返回非 JSON", status=resp.status_code) from exc
        code = payload.get("code")
        if code is not None and code not in _OK_CODES:
            raise PlatformError(
                str(payload.get("message") or payload.get("msg") or f"主站 code={code}"),
                code=code,
                status=resp.status_code,
            )
        return payload

    async def _inner_request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        timeout: float = 60.0,
    ) -> dict[str, Any]:
        """Agent inner API（api-key 鉴权，非用户 token）。"""
        api_key = (self.settings.agent_coin_api_key or "").strip()
        if not api_key:
            raise PlatformError("未配置 AGENT_COIN_API_KEY")
        if not self.base_url:
            raise PlatformError("未配置 PLATFORM_API_URL")
        url = f"{self.base_url}/{path.lstrip('/')}"
        headers = {"Content-Type": "application/json", "api-key": api_key}
        try:
            async with httpx.AsyncClient(timeout=timeout) as cli:
                resp = await cli.request(method, url, headers=headers, json=json_body)
        except httpx.HTTPError as exc:
            raise PlatformError(f"主站 Agent 请求失败: {exc}") from exc
        if resp.status_code >= 500:
            raise PlatformError(f"主站 Agent {resp.status_code}", status=resp.status_code)
        try:
            payload = resp.json()
        except ValueError as exc:
            raise PlatformError("主站 Agent 返回非 JSON", status=resp.status_code) from exc
        code = payload.get("code")
        if code is not None and code not in _OK_CODES:
            raise PlatformError(
                str(payload.get("message") or payload.get("msg") or f"主站 Agent code={code}"),
                code=code,
                status=resp.status_code,
            )
        return payload

    async def deduct_agent_coin(
        self,
        user_id: str | int,
        coin_number: float,
        biz_no: str,
        *,
        remark: str = "",
    ) -> AgentCoinResult:
        """POST /inner/agent/coin/deduct — 幂等 biz_no，余额不足 code=-100。"""
        payload = await self._inner_request(
            "POST",
            "/inner/agent/coin/deduct",
            json_body={
                "user_id": int(user_id),
                "coin_number": int(coin_number) if coin_number == int(coin_number) else coin_number,
                "biz_no": biz_no,
                "remark": remark or f"agent video {biz_no}",
            },
        )
        data = payload.get("data") or {}
        return AgentCoinResult(
            order_sn=str(data.get("order_sn") or ""),
            user_id=int(data.get("user_id") or user_id),
            coin_number=float(data.get("coin_number") or coin_number),
            balance=float(data.get("balance") or 0),
        )

    async def refund_agent_coin(
        self,
        *,
        biz_no: str = "",
        order_sn: str = "",
    ) -> AgentCoinResult:
        """POST /inner/agent/coin/refund — 按扣币订单全额退回，幂等。"""
        if not biz_no.strip() and not order_sn.strip():
            raise PlatformError("退币须提供 biz_no 或 order_sn")
        body: dict[str, Any] = {}
        if biz_no.strip():
            body["biz_no"] = biz_no.strip()
        if order_sn.strip():
            body["order_sn"] = order_sn.strip()
        payload = await self._inner_request(
            "POST",
            "/inner/agent/coin/refund",
            json_body=body,
        )
        data = payload.get("data") or {}
        return AgentCoinResult(
            order_sn=str(data.get("order_sn") or order_sn),
            refund_coin=float(data.get("refund_coin") or 0),
            balance=float(data.get("balance") or 0),
        )

    async def get_user_info(self, token: str) -> UserProfile:
        """GET /user/getUserInfo — 鉴权 + 积分。"""
        payload = await self._request("GET", "/user/getUserInfo", token)
        data = payload.get("data") or payload
        if not isinstance(data, dict):
            raise PlatformError("主站 getUserInfo 返回格式异常")
        user_id = _extract_user_id(data)
        if not user_id:
            raise PlatformError("主站 getUserInfo 未返回 userId", code=payload.get("code"))
        return UserProfile(
            user_id=user_id,
            coin=float(data.get("coin") or 0),
            nickname=str(data.get("nickname") or data.get("nickName") or ""),
            avatar=str(data.get("avatar") or ""),
            email=str(data.get("email") or ""),
            raw=data,
        )

    async def list_media(
        self, token: str, *, page: int = 1, limit: int = 30
    ) -> dict[str, Any]:
        return await self._request(
            "GET", "/mediaLibs/list", token, params={"page": page, "limit": limit}
        )

    async def get_coin(self, token: str) -> float:
        return (await self.get_user_info(token)).coin

    async def get_video_task_cost(
        self,
        token: str,
        task_params: dict[str, Any],
        *,
        app_id: str = AI_VIDEO_APP_ID,
    ) -> dict[str, Any]:
        """POST /taskV2/getTaskCost — 返回 {cost, available_credits, cost_enough}。"""
        payload = await self._request(
            "POST",
            "/taskV2/getTaskCost",
            token,
            json_body={"app_id": app_id, "task_params": task_params},
        )
        data = payload.get("data")
        return data if isinstance(data, dict) else {}

    async def submit_image(
        self, token: str, *, prompt: str, reference_urls: list[str] | None = None,
        model: str = "seedream_50",
    ) -> dict[str, Any]:
        """POST /aiImage/create — 主站生图（agent platform provider 路径）。"""
        return await self._request(
            "POST", "/aiImage/create", token,
            json_body={
                "model": model,
                "prompt": prompt,
                "reference_images": reference_urls or [],
            },
        )

    async def poll_image(self, token: str, task_id: str) -> dict[str, Any]:
        return await self._request("GET", f"/aiImage/status/{task_id}", token)

    async def submit_video(
        self,
        token: str,
        task_params: dict[str, Any] | None = None,
        *,
        prompt: str = "",
        model_name: str = "happyhorse_1.0",
        first_frame_url: str = "",
        reference_urls: list[str] | None = None,
        duration_sec: int = 15,
        ratio: str = "9:16",
        resolution: str = "1080p",
        generate_audio: bool = True,
        quantity: int = 1,
        camera_fixed: bool = False,
    ) -> dict[str, Any]:
        """POST /v1/video/push — 主站生视频（计费走 Agent deduct，push 不再依赖自动扣积分）。

        可传入完整 task_params，或用关键字参数自动构造（见 build_video_task_params）。
        成功时 data.taskId 为父任务 ID，用于 queryTasks 轮询。
        """
        body = task_params or build_video_task_params(
            prompt=prompt,
            model_name=model_name,
            first_frame_url=first_frame_url,
            reference_urls=reference_urls,
            duration=duration_sec,
            ratio=ratio,
            resolution=resolution,
            generate_audio=generate_audio,
            quantity=quantity,
            camera_fixed=camera_fixed,
        )
        return await self._request("POST", "/v1/video/push", token, json_body=body)

    async def submit_video_task(self, token: str, task_params: dict[str, Any]) -> str:
        """提交视频并返回父 taskId。"""
        payload = await self.submit_video(token, task_params)
        data = payload.get("data") or {}
        task_id = data.get("taskId") or data.get("task_id")
        if not task_id:
            raise PlatformError("主站 /v1/video/push 未返回 taskId")
        return str(task_id)

    async def poll_video(self, token: str, task_id: str) -> dict[str, Any]:
        """POST /v1/video/queryTasks — body: {"taskId": "..."}。"""
        return await self._request(
            "POST",
            "/v1/video/queryTasks",
            token,
            json_body={"taskId": task_id},
        )

    async def poll_video_snapshot(self, token: str, task_id: str) -> VideoTaskSnapshot:
        return parse_video_task(await self.poll_video(token, task_id))


_client: PlatformClient | None = None


def get_platform_client() -> PlatformClient:
    global _client
    if _client is None:
        _client = PlatformClient()
    return _client
