"""把现有 SQLite（data/workflow.db）数据迁移到 PostgreSQL。

用法（PowerShell）：
  $env:DATABASE_URL="postgresql://vidau:vidau@localhost:5433/vidau_flow"
  python scripts/migrate_sqlite_to_pg.py

流程：在 PG 建表（若无）→ 逐表读 SQLite → 仅迁移两边都存在的列 →
INSERT ... ON CONFLICT (id) DO NOTHING（可重复执行，幂等）。
"""
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import psycopg  # noqa: E402

from src.db.database import get_db_path, init_db, is_postgres  # noqa: E402

TABLES = [
    "batches", "scripts", "prompts", "videos", "products",
    "content_directions", "accounts", "difficulty_levels", "users",
]


def _pg_columns(pg, table: str) -> set[str]:
    with pg.cursor() as cur:
        cur.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = %s",
            (table,),
        )
        return {r[0] for r in cur.fetchall()}


def main() -> None:
    if not is_postgres():
        print("请先设置 DATABASE_URL 为 postgresql://...，再运行本脚本")
        sys.exit(1)

    sqlite_path = get_db_path()
    if not sqlite_path.exists():
        print(f"找不到 SQLite 数据库：{sqlite_path}")
        sys.exit(1)

    init_db()  # 在 PG 建表

    url = os.environ["DATABASE_URL"]
    sconn = sqlite3.connect(sqlite_path)
    sconn.row_factory = sqlite3.Row
    pg = psycopg.connect(url)

    total = 0
    try:
        for table in TABLES:
            # SQLite 是否有该表
            exists = sconn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                (table,),
            ).fetchone()
            if not exists:
                print(f"[skip] SQLite 无表 {table}")
                continue

            rows = sconn.execute(f"SELECT * FROM {table}").fetchall()
            if not rows:
                print(f"[ok]   {table}: 0 行")
                continue

            sqlite_cols = [d[0] for d in sconn.execute(f"SELECT * FROM {table} LIMIT 0").description]
            pg_cols = _pg_columns(pg, table)
            cols = [c for c in sqlite_cols if c in pg_cols]
            placeholders = ", ".join(["%s"] * len(cols))
            collist = ", ".join(cols)
            sql = (
                f"INSERT INTO {table} ({collist}) VALUES ({placeholders}) "
                f"ON CONFLICT (id) DO NOTHING"
            )
            inserted = 0
            with pg.cursor() as cur:
                for row in rows:
                    cur.execute(sql, tuple(row[c] for c in cols))
                    inserted += cur.rowcount
            pg.commit()
            total += inserted
            print(f"[ok]   {table}: {len(rows)} 行 → 新增 {inserted}")
    finally:
        sconn.close()
        pg.close()

    print(f"迁移完成，共新增 {total} 行。")


if __name__ == "__main__":
    main()
