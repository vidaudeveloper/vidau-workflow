-- PostgreSQL 完整 schema（合并了 SQLite 基础表 + 所有增量迁移列）。
-- 全新 PG 库直接建表，无需再跑 SQLite 的 ALTER 增量迁移。

CREATE TABLE IF NOT EXISTS batches (
    id TEXT PRIMARY KEY,
    product TEXT NOT NULL,
    direction TEXT NOT NULL,
    count INTEGER NOT NULL,
    extra_instruction TEXT DEFAULT '',
    creator TEXT DEFAULT '',
    status TEXT DEFAULT '生成中',
    difficulty_level TEXT DEFAULT '低级',
    language TEXT DEFAULT '英语',
    owner_user_id TEXT DEFAULT '',
    use_first_frame INTEGER DEFAULT 0,
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
    difficulty_level TEXT DEFAULT '低级',
    account_id TEXT DEFAULT '',
    language TEXT DEFAULT '英语',
    producer TEXT DEFAULT '',
    delivery_status TEXT DEFAULT '',
    delivery_feedback TEXT DEFAULT '',
    fa_flag TEXT DEFAULT '0',
    use_first_frame INTEGER DEFAULT 0,
    created_at TEXT NOT NULL
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
    created_at TEXT NOT NULL
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
    producer TEXT DEFAULT '',
    delivery_feedback TEXT DEFAULT '',
    fa_flag TEXT DEFAULT '0',
    subtitle_align_status TEXT DEFAULT '',
    subtitle_align_detail TEXT DEFAULT '',
    first_frame_url TEXT DEFAULT '',
    first_frame_url_part_b TEXT DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS products (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    image_url TEXT DEFAULT '',
    image_urls_json TEXT DEFAULT '',
    product_specs TEXT DEFAULT '',
    selling_points TEXT DEFAULT '',
    daily_price TEXT DEFAULT '',
    promo_price TEXT DEFAULT '',
    purchase_link TEXT DEFAULT '',
    listing_status TEXT DEFAULT '',
    conversion_method TEXT DEFAULT '',
    product_specs_draft TEXT DEFAULT '',
    selling_points_draft TEXT DEFAULT '',
    product_specs_confirmed INTEGER DEFAULT 0,
    vision_analyzed_at TEXT DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS content_directions (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT DEFAULT '',
    short_code TEXT DEFAULT '',
    created_at TEXT NOT NULL
);

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
    conversion_method TEXT DEFAULT '',
    created_at TEXT NOT NULL
);

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
);

CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    display_name TEXT DEFAULT '',
    role TEXT DEFAULT 'editor',
    is_active INTEGER DEFAULT 1,
    is_test INTEGER DEFAULT 0,
    created_at TEXT NOT NULL
);
