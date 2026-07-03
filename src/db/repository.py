import json
from datetime import datetime, timezone
from typing import Any

from src.db.database import get_db


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_dict(row) -> dict[str, Any]:
    return dict(row) if row else {}


class Repository:
    # --- batches ---

    def create_batch(self, batch: dict[str, Any]) -> None:
        with get_db() as conn:
            conn.execute(
                """INSERT INTO batches
                   (id, product, direction, count, extra_instruction, creator, status,
                    difficulty_level, language, owner_user_id, use_first_frame, workflow_id,
                    created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    batch["id"],
                    batch["product"],
                    batch["direction"],
                    batch["count"],
                    batch.get("extra_instruction", ""),
                    batch.get("creator", ""),
                    batch.get("status", "生成中"),
                    batch.get("difficulty_level", "低级"),
                    batch.get("language", "英语"),
                    batch.get("owner_user_id", ""),
                    int(batch.get("use_first_frame", 0) or 0),
                    batch.get("workflow_id", ""),
                    batch.get("created_at", _now()),
                ),
            )

    def list_batches(
        self,
        *,
        owner_user_id: str | None = None,
        admin: bool = True,
    ) -> list[dict[str, Any]]:
        query = "SELECT * FROM batches"
        params: list[Any] = []
        if owner_user_id and not admin:
            query += " WHERE owner_user_id = ?"
            params.append(owner_user_id)
        query += " ORDER BY created_at DESC"
        with get_db() as conn:
            rows = conn.execute(query, params).fetchall()
        return [_row_to_dict(r) for r in rows]

    def update_batch_status(self, batch_id: str, status: str) -> None:
        with get_db() as conn:
            conn.execute("UPDATE batches SET status = ? WHERE id = ?", (status, batch_id))

    def get_batch(self, batch_id: str) -> dict[str, Any] | None:
        with get_db() as conn:
            row = conn.execute("SELECT * FROM batches WHERE id = ?", (batch_id,)).fetchone()
        return _row_to_dict(row) if row else None

    def delete_scripts_for_batch(self, batch_id: str) -> None:
        with get_db() as conn:
            conn.execute("DELETE FROM scripts WHERE batch_id = ?", (batch_id,))

    def delete_batch_cascade(self, batch_id: str) -> None:
        """删除批次及其脚本、Prompt、视频记录。"""
        with get_db() as conn:
            rows = conn.execute(
                "SELECT id FROM scripts WHERE batch_id = ?", (batch_id,)
            ).fetchall()
            script_ids = [(r["id"] if isinstance(r, dict) else r[0]) for r in rows]
            for script_id in script_ids:
                conn.execute("DELETE FROM videos WHERE script_id = ?", (script_id,))
                conn.execute("DELETE FROM prompts WHERE script_id = ?", (script_id,))
            conn.execute("DELETE FROM scripts WHERE batch_id = ?", (batch_id,))
            conn.execute("DELETE FROM batches WHERE id = ?", (batch_id,))

    def delete_script_downstream(self, script_id: str) -> None:
        """删除脚本关联的 Prompt 与视频（保留脚本本身）。"""
        with get_db() as conn:
            conn.execute("DELETE FROM videos WHERE script_id = ?", (script_id,))
            conn.execute("DELETE FROM prompts WHERE script_id = ?", (script_id,))

    # --- scripts ---

    def create_script(self, script: dict[str, Any]) -> None:
        shots = script.get("shots", [])
        with get_db() as conn:
            conn.execute(
                """INSERT INTO scripts
                   (id, batch_id, product, direction, theme, hook, outline, cta, shots_json,
                    review_status, review_note, reviewer, flow_status,
                    difficulty_level, account_id, language, producer,
                    delivery_status, delivery_feedback, fa_flag, use_first_frame, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    script["id"],
                    script["batch_id"],
                    script["product"],
                    script["direction"],
                    script.get("theme", ""),
                    script.get("hook", ""),
                    script.get("outline", ""),
                    script.get("cta", ""),
                    json.dumps(shots, ensure_ascii=False),
                    script.get("review_status", "待审核"),
                    script.get("review_note", ""),
                    script.get("reviewer", ""),
                    script.get("flow_status", "已生成"),
                    script.get("difficulty_level", "低级"),
                    script.get("account_id", ""),
                    script.get("language", "英语"),
                    script.get("producer", ""),
                    script.get("delivery_status", ""),
                    script.get("delivery_feedback", ""),
                    script.get("fa_flag", "0"),
                    int(script.get("use_first_frame", 0) or 0),
                    script.get("created_at", _now()),
                ),
            )

    def update_script(self, script_id: str, fields: dict[str, Any]) -> None:
        fields = dict(fields)
        if "shots" in fields:
            fields["shots_json"] = json.dumps(fields.pop("shots"), ensure_ascii=False)
        cols = ", ".join(f"{k} = ?" for k in fields)
        with get_db() as conn:
            conn.execute(f"UPDATE scripts SET {cols} WHERE id = ?", (*fields.values(), script_id))

    def get_script(self, script_id: str) -> dict[str, Any] | None:
        with get_db() as conn:
            row = conn.execute("SELECT * FROM scripts WHERE id = ?", (script_id,)).fetchone()
        if not row:
            return None
        d = _row_to_dict(row)
        d["shots"] = json.loads(d.pop("shots_json", "[]") or "[]")
        return d

    def list_scripts(
        self,
        *,
        review_status: str | None = None,
        batch_id: str | None = None,
        owner_user_id: str | None = None,
        admin: bool = True,
    ) -> list[dict[str, Any]]:
        if owner_user_id and not admin:
            query = """SELECT s.* FROM scripts s
                         JOIN batches b ON b.id = s.batch_id
                         WHERE b.owner_user_id = ?"""
            params: list[Any] = [owner_user_id]
        else:
            query = "SELECT s.* FROM scripts s WHERE 1=1"
            params = []
        if review_status:
            query += " AND s.review_status = ?"
            params.append(review_status)
        if batch_id:
            query += " AND s.batch_id = ?"
            params.append(batch_id)
        query += " ORDER BY s.created_at DESC"
        with get_db() as conn:
            rows = conn.execute(query, params).fetchall()
        result = []
        for row in rows:
            d = _row_to_dict(row)
            d["shots"] = json.loads(d.pop("shots_json", "[]") or "[]")
            result.append(d)
        return result

    # --- prompts ---

    def create_prompt(self, prompt: dict[str, Any]) -> None:
        with get_db() as conn:
            conn.execute(
                """INSERT INTO prompts
                   (id, script_id, output_mode, prompt_text, prompt_part_b, product_spec_json,
                    negative_prompt, duration_sec, segment_duration_sec, aspect_ratio,
                    review_status, review_note, flow_status, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    prompt["id"],
                    prompt["script_id"],
                    prompt.get("output_mode", "待决定"),
                    prompt.get("prompt_text", ""),
                    prompt.get("prompt_part_b", ""),
                    prompt.get("product_spec_json", ""),
                    prompt.get("negative_prompt", ""),
                    prompt.get("duration_sec", 30),
                    prompt.get("segment_duration_sec", 15),
                    prompt.get("aspect_ratio", "9:16"),
                    prompt.get("review_status", "待审核"),
                    prompt.get("review_note", ""),
                    prompt.get("flow_status", "已生成"),
                    prompt.get("created_at", _now()),
                ),
            )

    def update_prompt(self, prompt_id: str, fields: dict[str, Any]) -> None:
        cols = ", ".join(f"{k} = ?" for k in fields)
        with get_db() as conn:
            conn.execute(f"UPDATE prompts SET {cols} WHERE id = ?", (*fields.values(), prompt_id))

    def get_prompt(self, prompt_id: str) -> dict[str, Any] | None:
        with get_db() as conn:
            row = conn.execute("SELECT * FROM prompts WHERE id = ?", (prompt_id,)).fetchone()
        return _row_to_dict(row) if row else None

    def get_prompt_by_script(self, script_id: str) -> dict[str, Any] | None:
        with get_db() as conn:
            row = conn.execute(
                "SELECT * FROM prompts WHERE script_id = ? ORDER BY created_at DESC LIMIT 1",
                (script_id,),
            ).fetchone()
        return _row_to_dict(row) if row else None

    def list_prompts(
        self,
        *,
        review_status: str | None = None,
        owner_user_id: str | None = None,
        admin: bool = True,
    ) -> list[dict[str, Any]]:
        if owner_user_id and not admin:
            query = """SELECT p.* FROM prompts p
                         JOIN scripts s ON s.id = p.script_id
                         JOIN batches b ON b.id = s.batch_id
                         WHERE b.owner_user_id = ?"""
            params: list[Any] = [owner_user_id]
        else:
            query = "SELECT p.* FROM prompts p WHERE 1=1"
            params = []
        if review_status:
            query += " AND p.review_status = ?"
            params.append(review_status)
        query += " ORDER BY p.created_at DESC"
        with get_db() as conn:
            rows = conn.execute(query, params).fetchall()
        return [_row_to_dict(r) for r in rows]

    # --- videos ---

    def create_video(self, video: dict[str, Any]) -> None:
        with get_db() as conn:
            conn.execute(
                """INSERT INTO videos
                   (id, prompt_id, script_id, output_mode, video_url, subtitle_status,
                    output_status, fail_reason, note, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    video["id"],
                    video.get("prompt_id", ""),
                    video["script_id"],
                    video.get("output_mode", ""),
                    video.get("video_url", ""),
                    video.get("subtitle_status", "未开始"),
                    video.get("output_status", "排队中"),
                    video.get("fail_reason", ""),
                    video.get("note", ""),
                    video.get("created_at", _now()),
                ),
            )

    def update_video(self, video_id: str, fields: dict[str, Any]) -> None:
        cols = ", ".join(f"{k} = ?" for k in fields)
        with get_db() as conn:
            conn.execute(f"UPDATE videos SET {cols} WHERE id = ?", (*fields.values(), video_id))

    def list_videos(
        self,
        *,
        owner_user_id: str | None = None,
        admin: bool = True,
    ) -> list[dict[str, Any]]:
        if owner_user_id and not admin:
            query = """SELECT v.* FROM videos v
                         JOIN scripts s ON s.id = v.script_id
                         JOIN batches b ON b.id = s.batch_id
                         WHERE b.owner_user_id = ?
                         ORDER BY v.created_at DESC"""
            params: list[Any] = [owner_user_id]
        else:
            query = "SELECT * FROM videos ORDER BY created_at DESC"
            params = []
        with get_db() as conn:
            rows = conn.execute(query, params).fetchall()
        return [_row_to_dict(r) for r in rows]

    def get_video(self, video_id: str) -> dict[str, Any] | None:
        with get_db() as conn:
            row = conn.execute("SELECT * FROM videos WHERE id = ?", (video_id,)).fetchone()
        return _row_to_dict(row) if row else None

    def delete_video(self, video_id: str) -> None:
        with get_db() as conn:
            conn.execute("DELETE FROM videos WHERE id = ?", (video_id,))

    @staticmethod
    def script_summary(script: dict[str, Any]) -> str:
        return json.dumps(
            {"theme": script.get("theme", ""), "hook": script.get("hook", ""), "outline": script.get("outline", "")},
            ensure_ascii=False,
        )

    # --- products ---

    def create_product(self, product: dict[str, Any]) -> None:
        with get_db() as conn:
            conn.execute(
                """INSERT INTO products
                   (id, name, image_url, image_urls_json, product_specs, product_specs_confirmed,
                    selling_points, daily_price, promo_price, purchase_link, listing_status,
                    conversion_method, brand, brand_pronunciation, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    product["id"],
                    product["name"],
                    product.get("image_url", ""),
                    product.get("image_urls_json", ""),
                    product.get("product_specs", ""),
                    int(product.get("product_specs_confirmed") or 0),
                    product.get("selling_points", ""),
                    product.get("daily_price", ""),
                    product.get("promo_price", ""),
                    product.get("purchase_link", ""),
                    product.get("listing_status", ""),
                    product.get("conversion_method", ""),
                    product.get("brand", ""),
                    product.get("brand_pronunciation", ""),
                    product.get("created_at", _now()),
                ),
            )

    def update_product(self, product_id: str, fields: dict[str, Any]) -> None:
        cols = ", ".join(f"{k} = ?" for k in fields)
        with get_db() as conn:
            conn.execute(f"UPDATE products SET {cols} WHERE id = ?", (*fields.values(), product_id))

    def delete_product(self, product_id: str) -> None:
        with get_db() as conn:
            conn.execute("DELETE FROM products WHERE id = ?", (product_id,))

    def list_products(self) -> list[dict[str, Any]]:
        with get_db() as conn:
            rows = conn.execute("SELECT * FROM products ORDER BY created_at DESC").fetchall()
        return [_row_to_dict(r) for r in rows]

    def get_product(self, product_id: str) -> dict[str, Any] | None:
        with get_db() as conn:
            row = conn.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
        return _row_to_dict(row) if row else None

    # --- content_directions ---

    def create_direction(self, direction: dict[str, Any]) -> None:
        with get_db() as conn:
            conn.execute(
                """INSERT INTO content_directions (id, name, description, short_code, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    direction["id"],
                    direction["name"],
                    direction.get("description", ""),
                    direction.get("short_code", ""),
                    direction.get("created_at", _now()),
                ),
            )

    def update_direction(self, direction_id: str, fields: dict[str, Any]) -> None:
        cols = ", ".join(f"{k} = ?" for k in fields)
        with get_db() as conn:
            conn.execute(f"UPDATE content_directions SET {cols} WHERE id = ?", (*fields.values(), direction_id))

    def delete_direction(self, direction_id: str) -> None:
        with get_db() as conn:
            conn.execute("DELETE FROM content_directions WHERE id = ?", (direction_id,))

    def list_directions(self) -> list[dict[str, Any]]:
        with get_db() as conn:
            rows = conn.execute("SELECT * FROM content_directions ORDER BY created_at DESC").fetchall()
        return [_row_to_dict(r) for r in rows]

    def get_direction(self, direction_id: str) -> dict[str, Any] | None:
        with get_db() as conn:
            row = conn.execute("SELECT * FROM content_directions WHERE id = ?", (direction_id,)).fetchone()
        return _row_to_dict(row) if row else None

    def get_direction_by_short_code(self, code: str) -> dict[str, Any] | None:
        with get_db() as conn:
            row = conn.execute(
                "SELECT * FROM content_directions WHERE short_code = ? LIMIT 1", (code,)
            ).fetchone()
        return _row_to_dict(row) if row else None

    def get_product_by_name(self, name: str) -> dict[str, Any] | None:
        with get_db() as conn:
            row = conn.execute("SELECT * FROM products WHERE name = ? LIMIT 1", (name,)).fetchone()
        return _row_to_dict(row) if row else None

    # --- accounts ---

    def create_account(self, account: dict[str, Any]) -> None:
        with get_db() as conn:
            conn.execute(
                """INSERT INTO accounts
                   (id, no, display_name, username, language, blogger_type, positioning,
                    content_directions, page_packaging, main_products, persona_style,
                    avatar_desc, bio, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    account["id"],
                    account.get("no", 0),
                    account["display_name"],
                    account.get("username", ""),
                    account.get("language", "英语"),
                    account.get("blogger_type", ""),
                    account.get("positioning", ""),
                    account.get("content_directions", ""),
                    account.get("page_packaging", ""),
                    account.get("main_products", ""),
                    account.get("persona_style", ""),
                    account.get("avatar_desc", ""),
                    account.get("bio", ""),
                    account.get("created_at", _now()),
                ),
            )

    def update_account(self, account_id: str, fields: dict[str, Any]) -> None:
        cols = ", ".join(f"{k} = ?" for k in fields)
        with get_db() as conn:
            conn.execute(f"UPDATE accounts SET {cols} WHERE id = ?", (*fields.values(), account_id))

    def delete_account(self, account_id: str) -> None:
        with get_db() as conn:
            conn.execute("DELETE FROM accounts WHERE id = ?", (account_id,))

    def list_accounts(self) -> list[dict[str, Any]]:
        with get_db() as conn:
            rows = conn.execute("SELECT * FROM accounts ORDER BY no ASC, created_at ASC").fetchall()
        return [_row_to_dict(r) for r in rows]

    def get_account(self, account_id: str) -> dict[str, Any] | None:
        with get_db() as conn:
            row = conn.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone()
        return _row_to_dict(row) if row else None

    def get_account_by_no(self, no: int) -> dict[str, Any] | None:
        with get_db() as conn:
            row = conn.execute("SELECT * FROM accounts WHERE no = ? LIMIT 1", (no,)).fetchone()
        return _row_to_dict(row) if row else None

    def list_difficulty_levels(self) -> list[dict[str, Any]]:
        with get_db() as conn:
            rows = conn.execute("SELECT * FROM difficulty_levels ORDER BY created_at").fetchall()
        return [_row_to_dict(r) for r in rows]

    def get_video_by_script(self, script_id: str) -> dict[str, Any] | None:
        with get_db() as conn:
            row = conn.execute(
                """SELECT * FROM videos WHERE script_id = ?
                   ORDER BY CASE WHEN id LIKE '%-manual' THEN 1 ELSE 0 END, created_at DESC
                   LIMIT 1""",
                (script_id,),
            ).fetchone()
        return _row_to_dict(row) if row else None

    def list_production_board(
        self,
        *,
        owner_user_id: str | None = None,
        admin: bool = True,
    ) -> list[dict[str, Any]]:
        owner_clause = ""
        params: list[Any] = []
        if owner_user_id and not admin:
            owner_clause = " AND b.owner_user_id = ?"
            params.append(owner_user_id)
        with get_db() as conn:
            rows = conn.execute(
                f"""SELECT s.*, a.display_name AS account_name, a.username AS account_username,
                          p.id AS prompt_id, p.review_status AS prompt_review_status,
                          p.output_mode AS prompt_output_mode,
                          v.id AS video_id, v.video_url, v.output_status, v.note AS video_note,
                          v.producer AS video_producer, v.delivery_feedback AS video_feedback,
                          v.fa_flag AS video_fa, v.segment_urls_json,
                          b.owner_user_id AS batch_owner_user_id, b.creator AS batch_creator
                   FROM scripts s
                   JOIN batches b ON b.id = s.batch_id
                   LEFT JOIN accounts a ON s.account_id = a.id
                   LEFT JOIN prompts p ON p.script_id = s.id
                   LEFT JOIN videos v ON v.script_id = s.id
                     AND v.id = (
                       SELECT v2.id FROM videos v2
                       WHERE v2.script_id = s.id
                       ORDER BY CASE WHEN v2.id LIKE '%-manual' THEN 1 ELSE 0 END,
                                v2.created_at DESC
                       LIMIT 1
                     )
                   WHERE 1=1{owner_clause}
                   ORDER BY s.created_at DESC""",
                params,
            ).fetchall()
        result = []
        for row in rows:
            d = _row_to_dict(row)
            d["shots"] = json.loads(d.pop("shots_json", "[]") or "[]")
            result.append(d)
        return result

    # --- users (系统登录) ---

    def count_users(self) -> int:
        with get_db() as conn:
            row = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()
        return int(row["c"]) if row else 0

    def create_user(self, user: dict[str, Any]) -> None:
        with get_db() as conn:
            conn.execute(
                """INSERT INTO users
                   (id, email, password_hash, display_name, role, is_active, is_test, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    user["id"],
                    user["email"].strip().lower(),
                    user["password_hash"],
                    user.get("display_name", ""),
                    user.get("role", "editor"),
                    1 if user.get("is_active", 1) else 0,
                    1 if user.get("is_test") else 0,
                    user.get("created_at", _now()),
                ),
            )

    def get_user(self, user_id: str) -> dict[str, Any] | None:
        with get_db() as conn:
            row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return _row_to_dict(row) if row else None

    def get_user_by_email(self, email: str) -> dict[str, Any] | None:
        with get_db() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE email = ?",
                (email.strip().lower(),),
            ).fetchone()
        return _row_to_dict(row) if row else None

    def list_users(self) -> list[dict[str, Any]]:
        with get_db() as conn:
            rows = conn.execute(
                "SELECT id, email, display_name, role, is_active, is_test, created_at FROM users ORDER BY created_at"
            ).fetchall()
        return [_row_to_dict(r) for r in rows]

    def update_user(self, user_id: str, fields: dict[str, Any]) -> None:
        allowed = {"email", "display_name", "role", "is_active", "password_hash", "is_test"}
        updates = {k: v for k, v in fields.items() if k in allowed and v is not None}
        if not updates:
            return
        if "email" in updates:
            updates["email"] = str(updates["email"]).strip().lower()
        cols = ", ".join(f"{k} = ?" for k in updates)
        with get_db() as conn:
            conn.execute(
                f"UPDATE users SET {cols} WHERE id = ?",
                (*updates.values(), user_id),
            )

    # --- workflow blueprints ---

    def create_reference_decomposition(self, row: dict[str, Any]) -> None:
        with get_db() as conn:
            conn.execute(
                """INSERT INTO reference_decompositions
                   (id, source_url, source_filename, payload_json, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    row["id"],
                    row.get("source_url", ""),
                    row.get("source_filename", ""),
                    row["payload_json"],
                    row.get("created_at", _now()),
                ),
            )

    def get_reference_decomposition(self, decomp_id: str) -> dict[str, Any] | None:
        with get_db() as conn:
            row = conn.execute(
                "SELECT * FROM reference_decompositions WHERE id = ?", (decomp_id,)
            ).fetchone()
        return _row_to_dict(row) if row else None

    def create_workflow_blueprint(self, row: dict[str, Any]) -> None:
        with get_db() as conn:
            conn.execute(
                """INSERT INTO workflow_blueprints
                   (id, product_id, product_name, status, reference_decomposition_id,
                    payload_json, confirmed_at, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    row["id"],
                    row.get("product_id", ""),
                    row.get("product_name", ""),
                    row.get("status", "draft"),
                    row.get("reference_decomposition_id", ""),
                    row["payload_json"],
                    row.get("confirmed_at", ""),
                    row.get("created_at", _now()),
                    row.get("updated_at", _now()),
                ),
            )

    def update_workflow_blueprint(self, workflow_id: str, fields: dict[str, Any]) -> None:
        if not fields:
            return
        cols = ", ".join(f"{k} = ?" for k in fields)
        with get_db() as conn:
            conn.execute(
                f"UPDATE workflow_blueprints SET {cols} WHERE id = ?",
                (*fields.values(), workflow_id),
            )

    def get_workflow_blueprint(self, workflow_id: str) -> dict[str, Any] | None:
        with get_db() as conn:
            row = conn.execute(
                "SELECT * FROM workflow_blueprints WHERE id = ?", (workflow_id,)
            ).fetchone()
        return _row_to_dict(row) if row else None

    def list_workflow_blueprints(
        self, *, product_id: str = "", limit: int = 50
    ) -> list[dict[str, Any]]:
        query = "SELECT * FROM workflow_blueprints"
        params: list[Any] = []
        if product_id:
            query += " WHERE product_id = ?"
            params.append(product_id)
        query += " ORDER BY updated_at DESC LIMIT ?"
        params.append(limit)
        with get_db() as conn:
            rows = conn.execute(query, params).fetchall()
        return [_row_to_dict(r) for r in rows]
