"""AdFlow MCP server.

A thin Model Context Protocol wrapper around the AdFlow FastAPI backend
(src/app.py). It exposes the intake -> product -> script -> review ->
storyboard -> review -> AI-video pipeline as MCP tools so a Hermes agent can
drive the whole workflow from chat, replacing the web UI. The pipeline is
product-agnostic: any product info (URL / files / text) can be ingested.

Design rules:
  * This server holds NO business logic and NO state. Every tool is a thin
    HTTP call to the backend running at ADFLOW_BASE_URL (default
    http://127.0.0.1:8787). The backend (WorkflowOrchestrator + Repository +
    SQLite + ffmpeg + Seedance polling) stays the single source of truth.
  * The backend must run headless with AUTH_ENABLED=false so these calls need
    no cookie/token.

Run modes:
    python server.py                    # stdio (local Hermes subprocess)
    python server.py --http             # standalone Streamable HTTP on :8790/mcp

Production: mounted on FastAPI at https://adflow.vidau.info/mcp (Hermes URL config).
Local stdio: Hermes config.yaml -> mcp_servers.adflow (command + args).
"""

from __future__ import annotations

import mimetypes
import os
from pathlib import Path
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

BASE_URL = os.environ.get("ADFLOW_BASE_URL", "http://127.0.0.1:8787").rstrip("/")
TIMEOUT = float(os.environ.get("ADFLOW_HTTP_TIMEOUT", "120"))
REVIEWER = os.environ.get("ADFLOW_REVIEWER", "hermes-agent")

# host=0.0.0.0 avoids localhost-only DNS rebinding guard when mounted on public domain.
# streamable_http_path="/" + FastAPI mount at /mcp => https://adflow.vidau.info/mcp
mcp = FastMCP("adflow", host="0.0.0.0", streamable_http_path="/")

# --- Review action -> backend status-string maps -------------------------
# The backend's review endpoints take an exact Chinese status string; we let
# the agent use stable English action verbs and translate here.
SCRIPT_ACTION_STATUS = {
    "approve": "通过",
    "reject": "不通过-废弃",
    "regenerate": "不通过-重生成",
    "manual": "不通过-人工剪辑",
}
PROMPT_ACTION_STATUS = {
    "approve": "通过",
    "reject": "不通过-废弃",
    "regenerate": "不通过-调Prompt",
    "manual": "不通过-改人工剪",
}


def _client() -> httpx.Client:
    return httpx.Client(base_url=BASE_URL, timeout=TIMEOUT)


def _raise_with_detail(r: httpx.Response) -> None:
    """Raise on HTTP error, surfacing the backend's error detail (not a bare
    status code) so the agent can see WHY a call failed and react/fix it."""
    if r.is_success:
        return
    detail = r.text
    try:
        body = r.json()
        if isinstance(body, dict) and "detail" in body:
            detail = body["detail"]
    except Exception:  # noqa: BLE001
        pass
    raise RuntimeError(f"{r.request.method} {r.request.url.path} -> {r.status_code}: {detail}")


def _get(path: str, params: dict[str, Any] | None = None) -> Any:
    with _client() as c:
        r = c.get(path, params=params)
        _raise_with_detail(r)
        return r.json()


def _post(path: str, json: dict[str, Any] | None = None) -> Any:
    with _client() as c:
        r = c.post(path, json=json or {})
        _raise_with_detail(r)
        return r.json() if r.content else {"ok": True}


def _patch(path: str, json: dict[str, Any] | None = None) -> Any:
    with _client() as c:
        r = c.patch(path, json=json or {})
        _raise_with_detail(r)
        return r.json() if r.content else {"ok": True}


def _delete(path: str) -> Any:
    with _client() as c:
        r = c.delete(path)
        _raise_with_detail(r)
        return r.json() if r.content else {"ok": True}


def _resolve_product_id(product: str) -> str:
    """Accept a product id OR a human name and return the backend product id.

    The batch endpoints validate `product` by id (repo.get_product = WHERE id=?),
    but agents/skills naturally pass names. We look the value up in /api/products:
    if it already matches an id we keep it, else we match by name (case- and
    space-insensitive). If nothing matches we return the original value and let
    the backend produce its own error.
    """
    raw = (product or "").strip()
    if not raw:
        return raw
    try:
        products = _get("/api/products")
    except Exception:  # noqa: BLE001
        return raw
    if not isinstance(products, list):
        return raw
    norm = raw.lower().replace(" ", "")
    for p in products:
        if str(p.get("id")) == raw:
            return raw
    for p in products:
        name = str(p.get("name") or "")
        if name.lower().replace(" ", "") == norm:
            return str(p.get("id"))
    return raw


_LEGACY_DIRECTION_MARKERS = (
    "功能解说",
    "痛点",
    "场景种草",
    "③",
    "④",
    "⑤",
    "⑥",
    "⑦",
    "⑧",
)
_DEFAULT_UGC_DIRECTION = "UGC Campaign"


def _ensure_confirmed_workflow(workflow_id: str) -> dict[str, Any]:
    """create_batch / run_autopilot 必须挂已确认的 Blueprint，禁止走默认产线。"""
    wid = (workflow_id or "").strip()
    if not wid:
        raise RuntimeError(
            "禁止无 workflow_id 建批次（会落到默认 30s 功能解说模板，与 UGC Blueprint 无关）。\n"
            "正确顺序：create_workflow_blueprint → patch_workflow_blueprint "
            "→ get_workflow_confirmation（给用户确认时长/音频/字幕）"
            " → confirm_workflow_blueprint → create_batch(workflow_id=...)。\n"
            "时长、单双段、原生/TTS、字幕、方向库均在 Blueprint 的 patch 里配置。"
        )
    bp = _get(f"/api/workflows/blueprints/{wid}")
    status = str(bp.get("status") or "")
    if status != "confirmed":
        raise RuntimeError(
            f"Blueprint {wid} 状态为 {status!r}，尚未 confirm。\n"
            "请先 get_workflow_confirmation 展示确认单，用户同意后再 confirm_workflow_blueprint。"
        )
    return bp


def _validate_batch_direction(direction: str, blueprint: dict[str, Any]) -> str:
    """Blueprint 含 direction_library 时，禁止旧版目录「⑤功能解说型」类方向名。"""
    batch = blueprint.get("batch") or {}
    has_variants = bool(
        (batch.get("direction_library") or "").strip() or batch.get("variant_scripts")
    )
    d = (direction or "").strip()
    if not has_variants:
        return d or _DEFAULT_UGC_DIRECTION
    if any(m in d for m in _LEGACY_DIRECTION_MARKERS):
        raise RuntimeError(
            f"方向 {direction!r} 是旧版内容目录（功能解说/痛点型），与 Blueprint "
            f"direction_library 冲突，会导致 30s 功能片而非 UGC 变体。\n"
            f"请改用 direction=\"{_DEFAULT_UGC_DIRECTION}\" 或 \"Product B-Roll Remix\"。\n"
            "各条 hook 由 direction_library / variant_scripts 按序号注入，勿在 direction 填 SOP 名。"
        )
    return d or _DEFAULT_UGC_DIRECTION


def _guard_batch_create(
    *,
    workflow_id: str,
    direction: str,
) -> tuple[dict[str, Any], str]:
    bp = _ensure_confirmed_workflow(workflow_id)
    safe_direction = _validate_batch_direction(direction, bp)
    return bp, safe_direction

@mcp.tool()
def list_products() -> Any:
    """List configured products (name, specs, selling points, prices).

    These are the fixed-config products a batch can be created against.
    """
    return _get("/api/products")


@mcp.tool()
def list_directions() -> Any:
    """List legacy catalog directions (e.g. 功能解说型).

    Do NOT pass these to create_batch when using a Workflow Blueprint with
    direction_library — use direction=\"UGC Campaign\" instead; hooks come from
    the blueprint library. Prefer the Blueprint flow (see adflow-blueprint skill).
    """
    return _get("/api/directions")


@mcp.tool()
def list_accounts() -> Any:
    """List publishing accounts / personas (drives voice + tone)."""
    return _get("/api/accounts")


@mcp.tool()
def get_meta() -> Any:
    """Catalog + auth metadata in one call: products, directions, accounts,
    difficulties, languages, delivery statuses, and current auth mode. Use this
    first to learn the valid option values before creating a batch."""
    return _get("/api/meta")


@mcp.tool()
def get_production_board() -> Any:
    """Wide production board: every script joined with its prompt and video
    status. The single best overview of what is in flight and what is stuck."""
    return _get("/api/production-board")


# =========================================================================
# Catalog WRITE — turn ANY product info into a batchable product
# -------------------------------------------------------------------------
# The product catalog is NOT a fixed set; it is just whatever has been
# ingested. To go from "user pasted a URL / dropped files" to "a batch can
# run", the normalized path is:
#   1) upload_product_images(local files)  -> image urls   (skip if you already
#                                                            have hosted urls)
#   2) create_product(name, image_urls=...) -> product_id
#   3) analyze_product_images(product_id)    -> AI spec draft from the photos
#      (optional: skip if you already have reliable specs text)
#   4) confirm_product_specs(product_id, product_specs=...) -> confirmed=1
# Only a product with confirmed specs AND >=1 image can be used by create_batch.
# =========================================================================
@mcp.tool()
def upload_product_images(file_paths: list[str]) -> Any:
    """Upload 1-9 local image files to the backend and get back hosted image
    URLs to use in create_product/update_product. Accepts absolute paths to
    image files. Total request size must stay under ~64MB."""
    files_multipart: list[tuple[str, tuple[str, bytes, str]]] = []
    missing: list[str] = []
    for raw in file_paths or []:
        p = Path(raw)
        if not p.is_file():
            missing.append(raw)
            continue
        ctype = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
        files_multipart.append(("files", (p.name, p.read_bytes(), ctype)))
    if missing:
        return {"error": "files not found", "missing": missing}
    if not files_multipart:
        return {"error": "no image files provided"}
    with _client() as c:
        r = c.post("/api/uploads/product-images", files=files_multipart)
        _raise_with_detail(r)
        return r.json()


@mcp.tool()
def create_product(
    name: str,
    brand: str = "",
    brand_pronunciation: str = "",
    image_urls: list[str] | None = None,
    product_specs: str = "",
    selling_points: str = "",
    daily_price: str = "",
    promo_price: str = "",
    purchase_link: str = "",
    conversion_method: str = "",
    product_specs_confirmed: bool = False,
) -> Any:
    """Create a product from arbitrary product info so it becomes batchable.

    `image_urls` (1-9, from upload_product_images or a product page) is REQUIRED
    by the backend. `product_specs` is the structured appearance/interface spec
    that drives the storyboard; if you don't have it yet, leave it empty, then
    call analyze_product_images + confirm_product_specs. Returns {"id": ...}.

    `brand` is the on-screen brand spelling (e.g. "Anker"); leave empty for an
    unbranded/neutral product. `brand_pronunciation` is an optional hint for how
    the voiceover should SAY the brand when the spelling is mispronounced by TTS
    (e.g. brand "BLUETTI" -> "blue tee"); leave empty to read it as written.

    Set product_specs_confirmed=True ONLY when product_specs is already accurate
    and human/agent-verified; otherwise confirm later via confirm_product_specs.
    """
    body = {
        "name": name,
        "brand": brand,
        "brand_pronunciation": brand_pronunciation,
        "image_urls": image_urls or [],
        "product_specs": product_specs,
        "selling_points": selling_points,
        "daily_price": daily_price,
        "promo_price": promo_price,
        "purchase_link": purchase_link,
        "conversion_method": conversion_method,
        "product_specs_confirmed": product_specs_confirmed,
    }
    return _post("/api/products", body)


@mcp.tool()
def update_product(
    product_id: str,
    name: str = "",
    brand: str = "",
    brand_pronunciation: str = "",
    image_urls: list[str] | None = None,
    product_specs: str = "",
    selling_points: str = "",
    daily_price: str = "",
    promo_price: str = "",
    purchase_link: str = "",
    conversion_method: str = "",
) -> Any:
    """Patch fields on an existing product. Only non-empty args are sent.
    NOTE: changing image_urls or product_specs resets product_specs_confirmed
    to 0, so re-confirm afterwards. `brand` / `brand_pronunciation` set the
    on-screen brand spelling and the voiceover pronunciation hint. Accepts a
    product id or name."""
    pid = _resolve_product_id(product_id)
    body: dict[str, Any] = {}
    if name:
        body["name"] = name
    if brand:
        body["brand"] = brand
    if brand_pronunciation:
        body["brand_pronunciation"] = brand_pronunciation
    if image_urls is not None:
        body["image_urls"] = image_urls
    if product_specs:
        body["product_specs"] = product_specs
    if selling_points:
        body["selling_points"] = selling_points
    if daily_price:
        body["daily_price"] = daily_price
    if promo_price:
        body["promo_price"] = promo_price
    if purchase_link:
        body["purchase_link"] = purchase_link
    if conversion_method:
        body["conversion_method"] = conversion_method
    if not body:
        return {"error": "nothing to update"}
    return _patch(f"/api/products/{pid}", body)


@mcp.tool()
def delete_product(product_id: str) -> Any:
    """Delete a product (e.g. a throwaway test case). Accepts id or name."""
    return _delete(f"/api/products/{_resolve_product_id(product_id)}")


@mcp.tool()
def analyze_product_images(product_id: str) -> Any:
    """Run vision analysis on a product's images to DRAFT structured specs +
    selling points (saved as product_specs_draft, confirmed stays 0). Use this
    when you don't have reliable specs text. Then review the draft and lock it
    with confirm_product_specs. Accepts a product id or name."""
    pid = _resolve_product_id(product_id)
    return _post(f"/api/products/{pid}/analyze-images")


@mcp.tool()
def analyze_images_preview(
    image_urls: list[str],
    product_name: str = "",
    existing_specs: str = "",
    existing_selling_points: str = "",
) -> Any:
    """Vision-analyze image URLs into a spec/selling-point draft WITHOUT
    creating a product first. Handy to preview what specs a set of photos yields
    before committing to create_product."""
    return _post(
        "/api/products/analyze-images",
        {
            "image_urls": image_urls,
            "product_name": product_name,
            "existing_specs": existing_specs,
            "existing_selling_points": existing_selling_points,
        },
    )


@mcp.tool()
def confirm_product_specs(
    product_id: str, product_specs: str, selling_points: str = ""
) -> Any:
    """Lock in a product's final specs (sets product_specs_confirmed=1), which
    is the gate create_batch requires. `product_specs` is the structured
    appearance/interface/demo-rule text the storyboard relies on and must be
    accurate. Accepts a product id or name."""
    pid = _resolve_product_id(product_id)
    return _post(
        f"/api/products/{pid}/confirm-specs",
        {"product_specs": product_specs, "selling_points": selling_points},
    )


# =========================================================================
# Cost estimate — preview spend BEFORE committing a batch
# =========================================================================
@mcp.tool()
def get_pricing() -> Any:
    """Billing/pricing info (plans, credit packs, purchase links). Use together
    with estimate_cost to tell the user roughly what a batch will cost."""
    return _get("/api/billing/pricing")


@mcp.tool()
def estimate_cost(
    brief: str,
    duration_sec: int = 15,
    ratio: str = "9:16",
    resolution: str = "1080p",
    model_name: str = "",
) -> Any:
    """Estimate the credit cost of generating ONE video segment for `brief`.
    Returns {estimated_credits, range, currency, provider, fallback}. A 30s ad
    is 2 segments (part_a + part_b), so multiply by 2 per video, then by the
    number of videos in the batch. `fallback=true` means it returned a coarse
    range because no live billing token was available."""
    return _post(
        "/api/toc/quick-generate/estimate",
        {
            "brief": brief,
            "duration_sec": duration_sec,
            "ratio": ratio,
            "resolution": resolution,
            "model_name": model_name,
        },
    )


# =========================================================================
# Batch lifecycle
# =========================================================================
@mcp.tool()
def list_batches() -> Any:
    """List batches with script counts and pending-review counts."""
    return _get("/api/batches")


@mcp.tool()
def create_batch(
    product: str,
    direction: str,
    count: int = 3,
    language: str = "英语",
    extra_instruction: str = "",
    difficulty_level: str = "低级",
    account_id: str = "",
    producer: str = "",
    use_first_frame: bool = False,
    workflow_id: str = "",
) -> Any:
    """Create a batch and generate scripts only (human review gates the rest).

    **Requires** a confirmed Workflow Blueprint: `workflow_id` is mandatory.
    Scripts are produced in the background; poll list_scripts(batch_id=...)
    until review_status is 待审核.

    Before calling: patch_workflow_blueprint (duration, audio, subtitles,
    direction_library) → get_workflow_confirmation → confirm_workflow_blueprint.

    `product` accepts name or id. `direction` is a batch label only when
    direction_library is set — use \"UGC Campaign\", not ⑤功能解说型.
    count is 1-20.
    """
    _, safe_direction = _guard_batch_create(workflow_id=workflow_id, direction=direction)
    body = {
        "product": _resolve_product_id(product),
        "direction": safe_direction,
        "count": count,
        "language": language,
        "extra_instruction": extra_instruction,
        "difficulty_level": difficulty_level,
        "account_id": account_id,
        "producer": producer,
        "use_first_frame": use_first_frame,
        "workflow_id": workflow_id,
    }
    return _post("/api/batches", body)


@mcp.tool()
def run_autopilot(
    product: str,
    direction: str,
    count: int = 3,
    language: str = "英语",
    extra_instruction: str = "",
    difficulty_level: str = "低级",
    account_id: str = "",
    producer: str = "",
    use_first_frame: bool = False,
    workflow_id: str = "",
) -> Any:
    """Create a batch and run the FULL pipeline with auto-approval (no human
    review gates). Prefer `confirm_and_run_production` after the user confirms
    the blueprint once — do NOT ask again before calling.

    Use only when the user explicitly wants hands-off generation all the way
    to finished video. Otherwise prefer create_batch + manual review.

    **Requires** confirmed `workflow_id` (same gates as create_batch).
    """
    _, safe_direction = _guard_batch_create(workflow_id=workflow_id, direction=direction)
    body = {
        "product": _resolve_product_id(product),
        "direction": safe_direction,
        "count": count,
        "language": language,
        "extra_instruction": extra_instruction,
        "difficulty_level": difficulty_level,
        "account_id": account_id,
        "producer": producer,
        "use_first_frame": use_first_frame,
        "workflow_id": workflow_id,
    }
    return _post("/api/batches/autopilot", body)


@mcp.tool()
def retry_batch(batch_id: str) -> Any:
    """Re-queue a failed batch's script generation."""
    return _post(f"/api/batches/{batch_id}/retry")


@mcp.tool()
def delete_batch(batch_id: str) -> Any:
    """Delete a failed batch."""
    return _delete(f"/api/batches/{batch_id}")


# =========================================================================
# Scripts + review
# =========================================================================
@mcp.tool()
def list_scripts(batch_id: str = "", review_status: str = "") -> Any:
    """List scripts, optionally filtered by batch_id and/or review_status
    (e.g. 待审核, 通过). Each script includes theme, hook, outline, cta, shots[]."""
    params: dict[str, Any] = {}
    if batch_id:
        params["batch_id"] = batch_id
    if review_status:
        params["review_status"] = review_status
    return _get("/api/scripts", params or None)


@mcp.tool()
def get_script(script_id: str) -> Any:
    """Full script detail including shot list. Read this before reviewing."""
    return _get(f"/api/scripts/{script_id}")


@mcp.tool()
def review_script(script_id: str, action: str, note: str = "") -> Any:
    """Review a script. action is one of:
      approve    -> advance to storyboard prompt
      reject     -> discard
      regenerate -> regenerate the script (note REQUIRED: what to change)
      manual     -> route to manual editing (no AI video)
    Read the script with get_script first and judge it against the review skill.
    """
    status = SCRIPT_ACTION_STATUS.get(action)
    if status is None:
        return {"error": f"invalid action '{action}', expected one of {list(SCRIPT_ACTION_STATUS)}"}
    if action == "regenerate" and not note.strip():
        return {"error": "note is required when action=regenerate (say what to change)"}
    return _post(
        f"/api/scripts/{script_id}/review",
        {"status": status, "note": note, "reviewer": REVIEWER},
    )


# =========================================================================
# Storyboard prompts + review
# =========================================================================
@mcp.tool()
def list_prompts(review_status: str = "") -> Any:
    """List storyboard prompts, optionally filtered by review_status (待审核, 通过)."""
    params = {"review_status": review_status} if review_status else None
    return _get("/api/prompts", params)


@mcp.tool()
def get_prompt(prompt_id: str) -> Any:
    """Full storyboard prompt detail (prompt_text, prompt_part_b, product_spec,
    negative_prompt, duration) plus the source script. Read before reviewing."""
    return _get(f"/api/prompts/{prompt_id}")


@mcp.tool()
def review_prompt(prompt_id: str, action: str, note: str = "") -> Any:
    """Review a storyboard prompt. action is one of:
      approve    -> queue AI video generation (2x15s + concat)
      reject     -> discard
      regenerate -> regenerate the prompt (note recommended)
      manual     -> route to manual editing
    Read the prompt with get_prompt first.
    """
    status = PROMPT_ACTION_STATUS.get(action)
    if status is None:
        return {"error": f"invalid action '{action}', expected one of {list(PROMPT_ACTION_STATUS)}"}
    return _post(f"/api/prompts/{prompt_id}/review", {"status": status, "note": note})


# =========================================================================
# Videos
# =========================================================================
@mcp.tool()
def list_videos() -> Any:
    """List videos with output_status (排队中/生成中/待交付/待剪辑/失败),
    subtitle_status, video_url, fail_reason, and source script fields."""
    return _get("/api/videos")


@mcp.tool()
def get_video(video_id: str) -> Any:
    """Get a single video's current state (filtered from the video list)."""
    videos = _get("/api/videos")
    if isinstance(videos, list):
        for v in videos:
            if str(v.get("id")) == str(video_id):
                return v
    return {"error": f"video {video_id} not found"}


@mcp.tool()
def retry_video(video_id: str) -> Any:
    """Retry a failed video generation."""
    return _post(f"/api/videos/{video_id}/retry")


@mcp.tool()
def recover_video(video_id: str) -> Any:
    """Recover a video stuck in 生成中 (re-attach to or re-poll the job)."""
    return _post(f"/api/videos/{video_id}/recover")


@mcp.tool()
def regenerate_segment(video_id: str, segment: str) -> Any:
    """Regenerate one 15s segment. segment must be 'part_a' or 'part_b'."""
    if segment not in ("part_a", "part_b"):
        return {"error": "segment must be 'part_a' or 'part_b'"}
    return _post(f"/api/videos/{video_id}/segments/{segment}/regenerate")


@mcp.tool()
def burn_subtitles(video_id: str) -> Any:
    """Burn ASS subtitles onto the finished video (background job)."""
    return _post(f"/api/videos/{video_id}/burn-subtitles")


# =========================================================================
# Delivery
# =========================================================================
@mcp.tool()
def get_package(script_id: str) -> Any:
    """Delivery package metadata for a script: final video_url, segments,
    downloadable asset filenames. Surface video_url so the user can preview it."""
    return _get(f"/api/scripts/{script_id}/package")


@mcp.tool()
def update_delivery(
    script_id: str,
    delivery_status: str = "",
    delivery_feedback: str = "",
    producer: str = "",
    fa_flag: str = "",
) -> Any:
    """Update a script's delivery status / feedback. delivery_status values come
    from get_meta().delivery_statuses (e.g. '', 可审核, ok)."""
    body: dict[str, Any] = {}
    if delivery_status:
        body["delivery_status"] = delivery_status
    if delivery_feedback:
        body["delivery_feedback"] = delivery_feedback
    if producer:
        body["producer"] = producer
    if fa_flag:
        body["fa_flag"] = fa_flag
    return _patch(f"/api/scripts/{script_id}/delivery", body)


# =========================================================================
# Intake / Copilot — reference materials -> structured brief
# =========================================================================
_VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".webm", ".avi", ".mkv"}


@mcp.tool()
def analyze_intake(
    user_note: str = "",
    product_hint: str = "",
    product_page_url: str = "",
    reference_video_url: str = "",
    file_paths: list[str] | None = None,
) -> Any:
    """Analyze reference materials into a structured creative brief (the chat
    equivalent of the web Copilot intake).

    Accepts any mix of:
      * free-text `user_note` (the user's ask; a video URL inside it is detected)
      * `product_hint` (which product this is about)
      * `product_page_url` (a listing/landing page to read)
      * `reference_video_url` (a competitor/reference video link)
      * `file_paths`: ABSOLUTE local paths to images / PDFs / a reference video.
        In Hermes Desktop the user can drag-drop files; pass their local paths
        here. Routing by extension: .pdf -> pdf field, video exts ->
        reference_video, everything else -> images.

    Returns a brief with: product_name, selling_points, product_specs_summary,
    reference_style, hook_patterns, suggested_brief, suggested_direction,
    confidence_notes, material_context, sources.

    **Next step is Blueprint, not create_batch:** map fields into
    patch_workflow_blueprint (creative / video_spec / batch), confirm, then
    create_batch(workflow_id=...). Do not feed suggested_direction into
    create_batch.direction when using direction_library.
    """
    files_multipart: list[tuple[str, tuple[str, bytes, str]]] = []
    missing: list[str] = []
    for raw in file_paths or []:
        p = Path(raw)
        if not p.is_file():
            missing.append(raw)
            continue
        data = p.read_bytes()
        ctype = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
        ext = p.suffix.lower()
        if ext == ".pdf":
            field = "pdf"
        elif ext in _VIDEO_EXTS:
            field = "reference_video"
        else:
            field = "files"
        files_multipart.append((field, (p.name, data, ctype)))

    if missing:
        return {"error": "files not found", "missing": missing}

    form = {
        "user_note": user_note,
        "product_hint": product_hint,
        "product_page_url": product_page_url,
        "reference_video_url": reference_video_url,
    }
    with _client() as c:
        r = c.post("/api/toc/intake/analyze", data=form, files=files_multipart or None)
        r.raise_for_status()
        return r.json()


# =========================================================================
# Workflow Blueprint — reference decompose + custom pipeline
# =========================================================================


@mcp.tool()
def decompose_reference_video(
    file_path: str,
    user_note: str = "",
    product_hint: str = "",
) -> Any:
    """Upload a local reference/competitor video and return structured decomposition
    (duration, pacing, hook type, narrative beats, recommended segment strategy).

    Pass ABSOLUTE path to .mp4/.mov etc. Returns decomposition_id for blueprint creation.
    """
    p = Path(file_path)
    if not p.is_file():
        return {"error": "file not found", "path": file_path}
    ext = p.suffix.lower()
    if ext not in _VIDEO_EXTS:
        return {"error": "unsupported video extension", "path": file_path}
    ctype = mimetypes.guess_type(p.name)[0] or "video/mp4"
    data = p.read_bytes()
    with _client() as c:
        r = c.post(
            "/api/workflows/reference/decompose",
            data={"user_note": user_note, "product_hint": product_hint},
            files=[("reference_video", (p.name, data, ctype))],
            timeout=300,
        )
        _raise_with_detail(r)
        return r.json()


@mcp.tool()
def learn_reference_style(
    video_paths: list[str],
    product_image_paths: list[str] | None = None,
    user_note: str = "",
    product_hint: str = "",
) -> Any:
    """Learn UGC creator persona, product visual truth, and CTA from multiple reference
    TikTok videos plus optional product still photos (powder color/packaging from photos).

    Pass ABSOLUTE paths. Returns decomposition_id for create_workflow_blueprint().
    """
    files: list[tuple[str, tuple[str, bytes, str]]] = []
    for path in video_paths:
        p = Path(path)
        if not p.is_file():
            return {"error": "video not found", "path": path}
        ext = p.suffix.lower()
        if ext not in _VIDEO_EXTS:
            return {"error": "unsupported video extension", "path": path}
        ctype = mimetypes.guess_type(p.name)[0] or "video/mp4"
        files.append(("reference_videos", (p.name, p.read_bytes(), ctype)))
    for path in product_image_paths or []:
        p = Path(path)
        if not p.is_file():
            continue
        ctype = mimetypes.guess_type(p.name)[0] or "image/png"
        files.append(("product_images", (p.name, p.read_bytes(), ctype)))
    if not files:
        return {"error": "no valid reference videos"}
    with _client() as c:
        r = c.post(
            "/api/workflows/reference/learn-style",
            data={"user_note": user_note, "product_hint": product_hint},
            files=files,
            timeout=900,
        )
        _raise_with_detail(r)
        return r.json()


@mcp.tool()
def create_workflow_blueprint(
    decomposition_id: str,
    product_id: str = "",
    product_name: str = "",
    reference_mode: str = "structure_clone",
    platform: str = "tiktok",
    goal: str = "traffic",
) -> Any:
    """Build a draft Workflow Blueprint from a reference decomposition + product."""
    return _post(
        "/api/workflows/blueprints/from-decomposition",
        {
            "decomposition_id": decomposition_id,
            "product_id": _resolve_product_id(product_id) if product_id else "",
            "product_name": product_name,
            "reference_mode": reference_mode,
            "platform": platform,
            "goal": goal,
        },
    )


@mcp.tool()
def get_workflow_blueprint(workflow_id: str) -> Any:
    """Fetch full Workflow Blueprint JSON."""
    return _get(f"/api/workflows/blueprints/{workflow_id}")


@mcp.tool()
def get_workflow_confirmation(workflow_id: str) -> Any:
    """Human-readable production confirmation sheet — show to user before spend."""
    return _get(f"/api/workflows/blueprints/{workflow_id}/confirmation")


@mcp.tool()
def confirm_workflow_blueprint(workflow_id: str) -> Any:
    """Lock blueprint after user explicitly confirms. Required before create_batch(workflow_id=...)."""
    return _post(f"/api/workflows/blueprints/{workflow_id}/confirm")


@mcp.tool()
def confirm_and_run_production(
    workflow_id: str,
    product: str,
    direction: str,
    count: int = 1,
    language: str = "英语",
    extra_instruction: str = "",
    difficulty_level: str = "低级",
    account_id: str = "",
    producer: str = "",
    use_first_frame: bool = False,
) -> Any:
    """Atomically confirm blueprint + start full autopilot pipeline in ONE call.

    **Use THIS immediately after the user says 确认 / OK / 开始 / 批准 once.**
    Do NOT ask again ("可以开始吗?"), do NOT pause for script or prompt review
    unless the user explicitly set review_mode=manual before confirming.

    Locks blueprint (if still draft), then POST /api/batches/autopilot with
    auto-approval through to finished video. Returns batch_id + status.
    Poll get_production_board once — avoid repeated "稍等" polling spam.
    """
    wid = (workflow_id or "").strip()
    if not wid:
        raise RuntimeError(
            "workflow_id is required. Complete patch → get_workflow_confirmation first."
        )
    bp = _get(f"/api/workflows/blueprints/{wid}")
    confirm_result: Any = {"status": bp.get("status"), "skipped": True}
    if str(bp.get("status") or "") != "confirmed":
        confirm_result = _post(f"/api/workflows/blueprints/{wid}/confirm")
        confirm_result = {"status": "confirmed", "result": confirm_result}
    _, safe_direction = _guard_batch_create(workflow_id=wid, direction=direction)
    body = {
        "product": _resolve_product_id(product),
        "direction": safe_direction,
        "count": count,
        "language": language,
        "extra_instruction": extra_instruction,
        "difficulty_level": difficulty_level,
        "account_id": account_id,
        "producer": producer,
        "use_first_frame": use_first_frame,
        "workflow_id": wid,
    }
    batch_result = _post("/api/batches/autopilot", body)
    batch_id = ""
    if isinstance(batch_result, dict):
        batch_id = str(batch_result.get("batch_id") or batch_result.get("id") or "")
    return {
        "workflow_id": wid,
        "confirmed": confirm_result,
        "batch": batch_result,
        "batch_id": batch_id,
        "status": "autopilot_started",
        "next": "Poll get_production_board once; report when videos are ready or failed.",
    }


@mcp.tool()
def get_production_options(native_audio: bool = True) -> Any:
    """Subtitle / audio combination options for patch_workflow_blueprint.

    Call before patch when user has not chosen duration or subtitles yet.
    """
    return _get("/api/workflows/production-options", params={"native_audio": native_audio})


@mcp.tool()
def patch_workflow_blueprint(
    workflow_id: str,
    product_id: str = "",
    video_spec: dict[str, Any] | None = None,
    production: dict[str, Any] | None = None,
    creative: dict[str, Any] | None = None,
    batch: dict[str, Any] | None = None,
) -> Any:
    """Update draft blueprint fields (duration, first-frame, acceptance points, etc.)."""
    body: dict[str, Any] = {}
    if product_id:
        body["product_id"] = _resolve_product_id(product_id)
    if video_spec:
        body["video_spec"] = video_spec
    if production:
        body["production"] = production
    if creative:
        body["creative"] = creative
    if batch:
        body["batch"] = batch
    return _patch(f"/api/workflows/blueprints/{workflow_id}", body)


# =========================================================================
# Workflow canvas — Hermes preview
# =========================================================================


def _fetch_canvas_state(batch_id: str = "", script_id: str = "") -> dict[str, Any]:
    params: dict[str, str] = {}
    if batch_id.strip():
        params["batch_id"] = batch_id.strip()
    if script_id.strip():
        params["script_id"] = script_id.strip()
    return _get("/api/canvas/state", params=params or None)


@mcp.tool()
def get_workflow_canvas(batch_id: str = "", script_id: str = "") -> Any:
    """Return the AdFlow workflow canvas as structured JSON (nodes, edges, status).

    Use after create_batch / run_autopilot to see where the pipeline is.
    Empty batch_id uses the latest batch."""
    return _fetch_canvas_state(batch_id, script_id)


def _canvas_mermaid(state: dict[str, Any]) -> str:
    icon = {"idle": "⏳", "running": "🔄", "done": "✅", "fail": "❌"}
    lines = ["flowchart LR"]
    for n in state.get("nodes") or []:
        nid = n["id"]
        label = n.get("label") or nid
        st = n.get("status") or "idle"
        summary = (n.get("summary") or "").replace('"', "'")[:40]
        lines.append(f'  {nid}["{icon.get(st, "")} {label}<br/>{summary}"]')
    for e in state.get("edges") or []:
        lines.append(f'  {e["from"]} --> {e["to"]}')
    return "\n".join(lines)


@mcp.tool()
def show_workflow_canvas(batch_id: str = "", script_id: str = "") -> Any:
    """Visual workflow canvas — for Hermes you MUST browser_navigate(preview_url).

    Do NOT summarize nodes as a markdown table. After this tool returns,
    call browser_navigate on preview_url (/hermes/canvas) for interactive UI:
    pan, zoom, drag nodes, click for details."""
    state = _fetch_canvas_state(batch_id, script_id)
    bid = state.get("batch_id") or batch_id.strip()
    base = BASE_URL.rstrip("/")
    q = f"?batch_id={bid}" if bid else ""
    preview = f"{base}/hermes/canvas{q}"
    svg_url = f"{base}/api/canvas/svg{q}"
    return {
        "preview_url": preview,
        "open_this_url": preview,
        "do_not_open": f"{base}/",
        "svg_url": svg_url,
        "batch_id": bid,
        "script_id": state.get("script_id", ""),
        "product": state.get("product", ""),
        "direction": state.get("direction", ""),
        "nodes": state.get("nodes", []),
        "mermaid": _canvas_mermaid(state),
        "hint": "Open preview_url (/hermes/canvas). Do not open the home page /.",
    }


@mcp.resource("adflow://canvas/{batch_id}", mime_type="image/svg+xml")
def workflow_canvas_resource(batch_id: str) -> str:
    """SVG snapshot of the workflow canvas for a batch."""
    with _client() as c:
        r = c.get("/api/canvas/svg", params={"batch_id": batch_id})
        _raise_with_detail(r)
        return r.text


# =========================================================================
# Health
# =========================================================================
@mcp.tool()
def health() -> Any:
    """Check the AdFlow backend is up and reachable at ADFLOW_BASE_URL."""
    try:
        with _client() as c:
            r = c.get("/health")
            return {"ok": r.status_code == 200, "status_code": r.status_code, "base_url": BASE_URL}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e), "base_url": BASE_URL}


if __name__ == "__main__":
    import sys

    if "--http" in sys.argv:
        import uvicorn

        port = int(os.environ.get("MCP_PORT", "8790"))
        uvicorn.run(mcp.streamable_http_app(), host="0.0.0.0", port=port)
    else:
        mcp.run()
