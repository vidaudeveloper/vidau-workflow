"""SQLite 增量迁移 — 兼容已有 workflow.db。"""

import sqlite3

_MIGRATIONS = [
    "ALTER TABLE products ADD COLUMN daily_price TEXT DEFAULT ''",
    "ALTER TABLE products ADD COLUMN promo_price TEXT DEFAULT ''",
    "ALTER TABLE products ADD COLUMN purchase_link TEXT DEFAULT ''",
    "ALTER TABLE products ADD COLUMN listing_status TEXT DEFAULT ''",
    "ALTER TABLE content_directions ADD COLUMN short_code TEXT DEFAULT ''",
    "ALTER TABLE batches ADD COLUMN difficulty_level TEXT DEFAULT '低级'",
    "ALTER TABLE batches ADD COLUMN language TEXT DEFAULT '英语'",
    "ALTER TABLE batches ADD COLUMN owner_user_id TEXT DEFAULT ''",
    "ALTER TABLE scripts ADD COLUMN difficulty_level TEXT DEFAULT '低级'",
    "ALTER TABLE scripts ADD COLUMN account_id TEXT DEFAULT ''",
    "ALTER TABLE scripts ADD COLUMN language TEXT DEFAULT '英语'",
    "ALTER TABLE scripts ADD COLUMN producer TEXT DEFAULT ''",
    "ALTER TABLE scripts ADD COLUMN delivery_status TEXT DEFAULT ''",
    "ALTER TABLE scripts ADD COLUMN delivery_feedback TEXT DEFAULT ''",
    "ALTER TABLE scripts ADD COLUMN fa_flag TEXT DEFAULT '0'",
    "ALTER TABLE videos ADD COLUMN producer TEXT DEFAULT ''",
    "ALTER TABLE videos ADD COLUMN delivery_feedback TEXT DEFAULT ''",
    "ALTER TABLE videos ADD COLUMN fa_flag TEXT DEFAULT '0'",
    "ALTER TABLE prompts ADD COLUMN prompt_part_b TEXT DEFAULT ''",
    "ALTER TABLE prompts ADD COLUMN segment_duration_sec INTEGER DEFAULT 15",
    "ALTER TABLE videos ADD COLUMN segment_urls_json TEXT DEFAULT ''",
    "ALTER TABLE products ADD COLUMN image_urls_json TEXT DEFAULT ''",
    "ALTER TABLE products ADD COLUMN product_specs TEXT DEFAULT ''",
    "ALTER TABLE prompts ADD COLUMN product_spec_json TEXT DEFAULT ''",
    "ALTER TABLE videos ADD COLUMN subtitle_align_status TEXT DEFAULT ''",
    "ALTER TABLE videos ADD COLUMN subtitle_align_detail TEXT DEFAULT ''",
    """
    CREATE TABLE IF NOT EXISTS accounts (
        id TEXT PRIMARY KEY,
        no INTEGER DEFAULT 0,
        display_name TEXT NOT NULL,
        username TEXT DEFAULT '',
        language TEXT DEFAULT '英语',
        blogger_type TEXT DEFAULT '',
        positioning TEXT DEFAULT '',
        content_directions TEXT DEFAULT '',
        page_packaging TEXT DEFAULT '',
        main_products TEXT DEFAULT '',
        persona_style TEXT DEFAULT '',
        avatar_desc TEXT DEFAULT '',
        bio TEXT DEFAULT '',
        created_at TEXT NOT NULL
    )
    """,
    "ALTER TABLE accounts ADD COLUMN conversion_method TEXT DEFAULT ''",
    "ALTER TABLE products ADD COLUMN conversion_method TEXT DEFAULT ''",
    "ALTER TABLE products ADD COLUMN product_specs_draft TEXT DEFAULT ''",
    "ALTER TABLE products ADD COLUMN selling_points_draft TEXT DEFAULT ''",
    "ALTER TABLE products ADD COLUMN product_specs_confirmed INTEGER DEFAULT 0",
    "ALTER TABLE products ADD COLUMN vision_analyzed_at TEXT DEFAULT ''",
    """
    CREATE TABLE IF NOT EXISTS difficulty_levels (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        reference_video TEXT DEFAULT '',
        core_form TEXT DEFAULT '',
        character TEXT DEFAULT '',
        background TEXT DEFAULT '',
        shot_count TEXT DEFAULT '',
        structure TEXT DEFAULT '',
        keywords TEXT DEFAULT '',
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS users (
        id TEXT PRIMARY KEY,
        email TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        display_name TEXT DEFAULT '',
        role TEXT DEFAULT 'editor',
        is_active INTEGER DEFAULT 1,
        created_at TEXT NOT NULL
    )
    """,
    "ALTER TABLE users ADD COLUMN is_test INTEGER DEFAULT 0",
    "ALTER TABLE batches ADD COLUMN use_first_frame INTEGER DEFAULT 0",
    "ALTER TABLE scripts ADD COLUMN use_first_frame INTEGER DEFAULT 0",
    "ALTER TABLE videos ADD COLUMN first_frame_url TEXT DEFAULT ''",
    "ALTER TABLE videos ADD COLUMN first_frame_url_part_b TEXT DEFAULT ''",
    # 品牌（按产品自带，使整条流水线与具体品牌无关）：brand=屏幕拼写，
    # brand_pronunciation=口播发音提示（如 BLUETTI→"blue tee"；留空则按拼写朗读）。
    "ALTER TABLE products ADD COLUMN brand TEXT DEFAULT ''",
    "ALTER TABLE products ADD COLUMN brand_pronunciation TEXT DEFAULT ''",
    """
    CREATE TABLE IF NOT EXISTS reference_decompositions (
        id TEXT PRIMARY KEY,
        source_url TEXT DEFAULT '',
        source_filename TEXT DEFAULT '',
        payload_json TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS workflow_blueprints (
        id TEXT PRIMARY KEY,
        product_id TEXT DEFAULT '',
        product_name TEXT DEFAULT '',
        status TEXT DEFAULT 'draft',
        reference_decomposition_id TEXT DEFAULT '',
        payload_json TEXT NOT NULL,
        confirmed_at TEXT DEFAULT '',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    "ALTER TABLE batches ADD COLUMN workflow_id TEXT DEFAULT ''",
]


_DATA_FIXES = [
    # 人工剪辑任务不应显示「排队中」（旧数据修正）
    """UPDATE videos SET output_status = '待剪辑'
       WHERE output_status = '排队中'
       AND (output_mode LIKE '%人工%' OR id LIKE '%-manual')""",
    # 无脚本或全部失败的批次不应永久停在「生成中」
    """UPDATE batches SET status = '生成失败'
       WHERE status = '生成中'
       AND (
         (SELECT COUNT(*) FROM scripts s WHERE s.batch_id = batches.id) = 0
         OR (
           (SELECT COUNT(*) FROM scripts s WHERE s.batch_id = batches.id AND s.review_status = '待审核') = 0
           AND (SELECT COUNT(*) FROM scripts s WHERE s.batch_id = batches.id AND s.review_status = '失败') > 0
         )
       )""",
    """UPDATE products SET conversion_method = 'Bio引流'
       WHERE IFNULL(conversion_method, '') = ''
       AND (
         LOWER(IFNULL(name, '')) LIKE '%fridge%'
         OR LOWER(IFNULL(listing_status, '')) LIKE '%不挂车%'
         OR LOWER(IFNULL(listing_status, '')) LIKE '%bio%'
       )""",
    """UPDATE products SET conversion_method = '视频挂链'
       WHERE IFNULL(conversion_method, '') = ''""",
    """UPDATE products SET product_specs_confirmed = 1
       WHERE IFNULL(product_specs, '') != ''
       AND IFNULL(product_specs_confirmed, 0) = 0""",
]


def run_migrations(conn: sqlite3.Connection) -> None:
    for sql in _MIGRATIONS:
        try:
            conn.execute(sql)
        except sqlite3.OperationalError:
            pass
    for sql in _DATA_FIXES:
        conn.execute(sql)
