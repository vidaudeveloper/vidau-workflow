"""从 Cindy Excel 逻辑导入种子数据。"""

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from src.config import ROOT
from src.db.database import get_db

EXCEL_JSON = ROOT / "data" / "excel_analysis.json"

DIRECTION_CODES = {
    "方向1": "①情感应急型",
    "方向2": "②开箱实测型",
    "方向3": "③场景对比型",
    "方向4": "④极端天气应急型",
    "方向5": "⑤功能解说型",
    "方向6": "⑥日常融入生活型",
}

PRODUCT_PRICES = {
    "Elite 300": ("2299", "1099", "https://www.tiktok.com/t/ZP9F5CCRLu2Sh-Rhd1Z/", ""),
    "Elite 100 V2": ("499", "449", "", ""),
    "Elite 100V2": ("499", "449", "", ""),
    "Apex 300": ("1699", "", "", ""),
    "Apex300+B300K": ("2799", "2499", "", ""),
    "FridgePower": ("", "", "https://www.kickstarter.com/projects/bluetti/fridgepower", "不挂车，bio放众筹链接"),
    "FRIDGEPOWER": ("", "", "https://www.kickstarter.com/projects/bluetti/fridgepower", "不挂车，bio放众筹链接"),
}

FRIDGEPOWER_SELLING_POINTS = """核心差异：UPS自动切换 + App远程提醒 + 薄型免改线安装
一级卖点：超薄机身(2.95in)、行业最低空载损耗4W、24H智能备电管家、NextGen UPS 10ms切换
二级卖点：智能家居兼容、1800W持续/3600W峰值、智能散热降噪30dB
定位：专为冰箱备电打造的超薄储能，不止冰箱还可带载鱼缸/污水泵等"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_accounts_from_json() -> list[dict]:
    if not EXCEL_JSON.exists():
        return []
    data = json.loads(EXCEL_JSON.read_text(encoding="utf-8"))
    sheet = data.get("账号人设", {}).get("preview", [])
    if len(sheet) < 2:
        return []
    headers = sheet[0]
    accounts = []
    for row in sheet[1:]:
        if not row or not row[0]:
            continue
        item = dict(zip(headers, row + [""] * (len(headers) - len(row))))
        accounts.append(item)
    return accounts


def seed_cindy_data() -> None:
    with get_db() as conn:
        # 难度等级
        if not conn.execute("SELECT 1 FROM difficulty_levels LIMIT 1").fetchone():
            diff = {}
            if EXCEL_JSON.exists():
                preview = json.loads(EXCEL_JSON.read_text(encoding="utf-8")).get("视频难度等级", {}).get(
                    "preview", []
                )
                for row in preview[1:]:
                    if row and row[0]:
                        diff[row[0]] = row[1] if len(row) > 1 else ""
            conn.execute(
                """INSERT INTO difficulty_levels
                   (id, name, reference_video, core_form, character, background, shot_count, structure, keywords, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    "low",
                    "低级",
                    diff.get("对标视频", ""),
                    diff.get("核心形式", "纯产品展示"),
                    diff.get("人物", "无"),
                    diff.get("背景/素材", "单一产品场景"),
                    diff.get("分镜数量", "少"),
                    diff.get("内容结构", "展示型"),
                    diff.get("判定关键词", "单一、简单、展示"),
                    _now(),
                ),
            )

        # 方向短码
        for code, name in DIRECTION_CODES.items():
            conn.execute(
                "UPDATE content_directions SET short_code = ? WHERE name = ?",
                (code, name),
            )

        # 产品价格与 FridgePower 卖点
        for row in conn.execute("SELECT id, name, selling_points FROM products").fetchall():
            name = row["name"]
            prices = None
            for key, val in PRODUCT_PRICES.items():
                if key.lower().replace(" ", "") in name.lower().replace(" ", ""):
                    prices = val
                    break
            fields: dict = {}
            if prices:
                fields["daily_price"] = prices[0]
                fields["promo_price"] = prices[1]
                fields["purchase_link"] = prices[2]
                fields["listing_status"] = prices[3]
            if "fridge" in name.lower() and not (row["selling_points"] or "").strip():
                fields["selling_points"] = FRIDGEPOWER_SELLING_POINTS
            if fields:
                cols = ", ".join(f"{k} = ?" for k in fields)
                conn.execute(f"UPDATE products SET {cols} WHERE id = ?", (*fields.values(), row["id"]))
            if "fridge" in name.lower():
                conn.execute(
                    "UPDATE products SET conversion_method = ? WHERE id = ?",
                    ("Bio引流", row["id"]),
                )

        # 账号人设
        if not conn.execute("SELECT 1 FROM accounts LIMIT 1").fetchone():
            for item in _load_accounts_from_json():
                conn.execute(
                    """INSERT INTO accounts
                       (id, no, display_name, username, language, blogger_type, positioning,
                        content_directions, page_packaging, main_products, persona_style,
                        avatar_desc, bio, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        str(uuid.uuid4())[:8],
                        int(item.get("No.", 0) or 0),
                        item.get("ID", ""),
                        item.get("username", ""),
                        item.get("语言", "英语"),
                        item.get("博主类型", ""),
                        item.get("账号定位", ""),
                        item.get("账号内容方向", ""),
                        item.get("主页包装", ""),
                        item.get("主推产品", ""),
                        item.get("账号人设风格", ""),
                        item.get("头像图片", ""),
                        item.get("bio/账号简介", ""),
                        _now(),
                    ),
                )
