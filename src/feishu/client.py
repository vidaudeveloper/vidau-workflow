import time
from typing import Any

import httpx

from src.config import Settings


class FeishuClient:
    BASE = "https://open.feishu.cn/open-apis"

    def __init__(self, settings: Settings):
        self.settings = settings
        self._token = ""
        self._token_expires = 0.0

    async def _ensure_token(self, client: httpx.AsyncClient) -> str:
        if self._token and time.time() < self._token_expires - 60:
            return self._token

        resp = await client.post(
            f"{self.BASE}/auth/v3/tenant_access_token/internal",
            json={
                "app_id": self.settings.feishu_app_id,
                "app_secret": self.settings.feishu_app_secret,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 0:
            raise RuntimeError(f"飞书鉴权失败: {data}")

        self._token = data["tenant_access_token"]
        self._token_expires = time.time() + data.get("expire", 7200)
        return self._token

    async def request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=60) as client:
            token = await self._ensure_token(client)
            resp = await client.request(
                method,
                f"{self.BASE}{path}",
                headers={"Authorization": f"Bearer {token}"},
                json=json,
                params=params,
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get("code") != 0:
                raise RuntimeError(f"飞书 API 错误 [{path}]: {data}")
            return data
