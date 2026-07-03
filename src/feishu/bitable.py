import json
from typing import Any

from src.config import Settings
from src.feishu.client import FeishuClient


class BitableService:
    def __init__(self, client: FeishuClient, settings: Settings):
        self.client = client
        self.settings = settings

    def _table(self, name: str) -> str:
        mapping = {
            "batch": self.settings.feishu_table_batch,
            "script": self.settings.feishu_table_script,
            "prompt": self.settings.feishu_table_prompt,
            "video": self.settings.feishu_table_video,
        }
        table_id = mapping.get(name, "")
        if not table_id:
            raise ValueError(f"未配置表 ID: {name}")
        return table_id

    async def create_records(self, table: str, records: list[dict[str, Any]]) -> list[str]:
        app = self.settings.feishu_bitable_app_token
        table_id = self._table(table)
        data = await self.client.request(
            "POST",
            f"/bitable/v1/apps/{app}/tables/{table_id}/records/batch_create",
            json={"records": [{"fields": r} for r in records]},
        )
        return [item["record_id"] for item in data.get("data", {}).get("records", [])]

    async def update_record(self, table: str, record_id: str, fields: dict[str, Any]) -> None:
        app = self.settings.feishu_bitable_app_token
        table_id = self._table(table)
        await self.client.request(
            "PUT",
            f"/bitable/v1/apps/{app}/tables/{table_id}/records/{record_id}",
            json={"fields": fields},
        )

    async def list_records(
        self,
        table: str,
        *,
        filter_expr: str | None = None,
        page_size: int = 100,
    ) -> list[dict[str, Any]]:
        app = self.settings.feishu_bitable_app_token
        table_id = self._table(table)
        params: dict[str, Any] = {"page_size": page_size}
        if filter_expr:
            params["filter"] = filter_expr

        items: list[dict[str, Any]] = []
        page_token: str | None = None
        while True:
            if page_token:
                params["page_token"] = page_token
            data = await self.client.request(
                "GET",
                f"/bitable/v1/apps/{app}/tables/{table_id}/records",
                params=params,
            )
            batch = data.get("data", {}).get("items", [])
            items.extend(batch)
            if not data.get("data", {}).get("has_more"):
                break
            page_token = data["data"].get("page_token")
        return items

    @staticmethod
    def field(record: dict[str, Any], name: str, default: str = "") -> str:
        fields = record.get("fields", {})
        val = fields.get(name, default)
        if isinstance(val, list) and val and isinstance(val[0], dict):
            return val[0].get("text", default)
        if isinstance(val, dict):
            return val.get("text", str(val))
        return str(val) if val is not None else default

    @staticmethod
    def shots_to_text(shots: list[dict[str, str]]) -> dict[str, str]:
        times, visuals, audios, overlays = [], [], [], []
        for s in shots:
            times.append(s.get("time", ""))
            visuals.append(s.get("visual", ""))
            audios.append(s.get("audio", ""))
            overlays.append(s.get("overlay", ""))
        return {
            "分镜-时长": "\n".join(times),
            "分镜-画面": "\n".join(visuals),
            "分镜-口播": "\n".join(audios),
            "分镜-花字": "\n".join(overlays),
        }

    @staticmethod
    def script_summary(fields: dict[str, Any]) -> str:
        return json.dumps(
            {
                "theme": fields.get("视频主题", ""),
                "hook": fields.get("Hook", ""),
                "outline": fields.get("内容大纲", ""),
            },
            ensure_ascii=False,
        )
