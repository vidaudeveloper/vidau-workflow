"""数据库连接层 — 支持 SQLite（默认）与 PostgreSQL（设置 DATABASE_URL 后启用）。

仓储层（repository.py）统一使用 sqlite3 风格的 `?` 占位符与 `conn.execute(...)`。
对 PostgreSQL，本模块提供一个薄适配器：
- 把 `?` 占位符转换为 `%s`，并在有参数时转义字面量 `%`；
- 用 psycopg3 的 dict_row，使行同时支持 dict(row) 与 row["col"]。
这样 repository.py 无需为两种后端写两套 SQL。
"""

import sqlite3
from contextlib import contextmanager
from pathlib import Path

from src.config import ROOT, get_settings


def get_db_path() -> Path:
    raw = (get_settings().database_path or "data/workflow.db").strip()
    path = Path(raw)
    return path if path.is_absolute() else ROOT / path


def _database_url() -> str:
    return (get_settings().database_url or "").strip()


def is_postgres() -> bool:
    return _database_url().lower().startswith(("postgres://", "postgresql://"))


DB_PATH = get_db_path()

_SCHEMA = """
CREATE TABLE IF NOT EXISTS batches (
    id TEXT PRIMARY KEY,
    product TEXT NOT NULL,
    direction TEXT NOT NULL,
    count INTEGER NOT NULL,
    extra_instruction TEXT DEFAULT '',
    creator TEXT DEFAULT '',
    status TEXT DEFAULT '生成中',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS scripts (
    id TEXT PRIMARY KEY,
    batch_id TEXT NOT NULL,
    product TEXT NOT NULL,
    direction TEXT NOT NULL,
    theme TEXT DEFAULT '',
    hook TEXT DEFAULT '',
    outline TEXT DEFAULT '',
    cta TEXT DEFAULT '',
    shots_json TEXT DEFAULT '[]',
    review_status TEXT DEFAULT '待审核',
    review_note TEXT DEFAULT '',
    reviewer TEXT DEFAULT '',
    flow_status TEXT DEFAULT '已生成',
    created_at TEXT NOT NULL,
    FOREIGN KEY (batch_id) REFERENCES batches(id)
);

CREATE TABLE IF NOT EXISTS prompts (
    id TEXT PRIMARY KEY,
    script_id TEXT NOT NULL,
    output_mode TEXT DEFAULT '待决定',
    prompt_text TEXT DEFAULT '',
    prompt_part_b TEXT DEFAULT '',
    product_spec_json TEXT DEFAULT '',
    negative_prompt TEXT DEFAULT '',
    duration_sec INTEGER DEFAULT 30,
    segment_duration_sec INTEGER DEFAULT 15,
    aspect_ratio TEXT DEFAULT '9:16',
    review_status TEXT DEFAULT '待审核',
    review_note TEXT DEFAULT '',
    flow_status TEXT DEFAULT '已生成',
    created_at TEXT NOT NULL,
    FOREIGN KEY (script_id) REFERENCES scripts(id)
);

CREATE TABLE IF NOT EXISTS videos (
    id TEXT PRIMARY KEY,
    prompt_id TEXT DEFAULT '',
    script_id TEXT NOT NULL,
    output_mode TEXT DEFAULT '',
    video_url TEXT DEFAULT '',
    subtitle_status TEXT DEFAULT '未开始',
    output_status TEXT DEFAULT '排队中',
    fail_reason TEXT DEFAULT '',
    note TEXT DEFAULT '',
    segment_urls_json TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    FOREIGN KEY (script_id) REFERENCES scripts(id)
);

CREATE TABLE IF NOT EXISTS products (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    image_url TEXT DEFAULT '',
    image_urls_json TEXT DEFAULT '',
    product_specs TEXT DEFAULT '',
    selling_points TEXT DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS content_directions (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT DEFAULT '',
    created_at TEXT NOT NULL
);
"""


def _translate_sql(sql: str, params) -> str:
    """sqlite `?` 占位符 → psycopg `%s`；有参数时字面量 `%` 需转义为 `%%`。"""
    if params:
        return sql.replace("%", "%%").replace("?", "%s")
    return sql


class _PgResult:
    def __init__(self, cur):
        self._cur = cur

    def fetchall(self):
        return self._cur.fetchall()

    def fetchone(self):
        return self._cur.fetchone()


class _PgConn:
    """让 psycopg3 连接表现得像 sqlite3.Connection（repository.py 所依赖的子集）。"""

    def __init__(self, conn):
        self._conn = conn

    def execute(self, sql: str, params=()):
        cur = self._conn.cursor()
        cur.execute(_translate_sql(sql, params), tuple(params) if params else None)
        return _PgResult(cur)

    def executescript(self, script: str):
        self._conn.execute(script)

    def commit(self):
        self._conn.commit()

    def close(self):
        self._conn.close()


def _pg_connect():
    import psycopg
    from psycopg.rows import dict_row

    return psycopg.connect(_database_url(), row_factory=dict_row)


def init_db() -> None:
    from src.db.migrations import run_migrations

    if is_postgres():
        schema_pg = (Path(__file__).parent / "schema_pg.sql").read_text(encoding="utf-8")
        raw = _pg_connect()
        try:
            raw.execute(schema_pg)
            raw.commit()
        finally:
            raw.close()
        return

    path = get_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.executescript(_SCHEMA)
        run_migrations(conn)
        conn.commit()


@contextmanager
def get_db():
    if is_postgres():
        raw = _pg_connect()
        conn = _PgConn(raw)
        try:
            yield conn
            raw.commit()
        finally:
            raw.close()
        return

    conn = sqlite3.connect(get_db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()
