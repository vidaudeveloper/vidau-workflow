"""集成自检：真实 FastAPI app 跑在 PostgreSQL 上，走 HTTP 端点验证无回归。

用法：
  $env:DATABASE_URL="postgresql://vidau:vidau@localhost:5433/vidau_flow"
  python scripts/_smoke_app.py
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "postgresql://vidau:vidau@localhost:5433/vidau_flow")
os.environ["AUTH_ENABLED"] = "false"  # 关掉登录门，专注验证 PG 数据读取
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

from src.app import app  # noqa: E402
from src.db.database import is_postgres  # noqa: E402

assert is_postgres(), "DATABASE_URL 未生效"

with TestClient(app) as client:
    meta = client.get("/api/meta")
    assert meta.status_code == 200, meta.text
    mj = meta.json()
    print("meta auth_mode =", mj.get("auth_mode"), "| products =", len(mj.get("products", [])),
          "| directions =", len(mj.get("directions", [])), "| accounts =", len(mj.get("accounts", [])))

    products = client.get("/api/products")
    assert products.status_code == 200, products.text
    print("/api/products ->", len(products.json()), "件")

    videos = client.get("/api/videos")
    assert videos.status_code == 200, videos.text
    print("/api/videos ->", len(videos.json()), "条")

    board = client.get("/api/production-board")
    assert board.status_code == 200, board.text
    bj = board.json()
    print("/api/production-board ->", len(bj), "行")
    if bj:
        sample = bj[0]
        assert isinstance(sample.get("shots"), list), "shots 未正确解析为列表"
        print("  样本 shots 字段类型 OK，字段数 =", len(sample))

print("APP-ON-PG SMOKE OK")
