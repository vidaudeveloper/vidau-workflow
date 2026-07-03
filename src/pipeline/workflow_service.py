"""Workflow Blueprint 持久化与确认闸门。"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from src.db.repository import Repository
from src.pipeline.workflow_blueprint import (
    WorkflowBlueprint,
    blueprint_from_decomposition,
    confirmation_sheet,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def blueprint_from_row(row: dict[str, Any] | None) -> WorkflowBlueprint | None:
    if not row:
        return None
    raw = row.get("payload_json") or "{}"
    bp = WorkflowBlueprint.from_storage(raw)
    if bp and not bp.workflow_id:
        bp.workflow_id = str(row.get("id") or "")
    return bp


def save_blueprint(repo: Repository, bp: WorkflowBlueprint) -> WorkflowBlueprint:
    bp.ensure_id()
    payload = json.dumps(bp.to_storage(), ensure_ascii=False)
    existing = repo.get_workflow_blueprint(bp.workflow_id)
    row = {
        "product_id": bp.product_id,
        "product_name": bp.product_name,
        "status": bp.status,
        "reference_decomposition_id": bp.reference.decomposition_id,
        "payload_json": payload,
        "updated_at": _now(),
    }
    if existing:
        repo.update_workflow_blueprint(bp.workflow_id, row)
    else:
        repo.create_workflow_blueprint(
            {
                "id": bp.workflow_id,
                **row,
                "confirmed_at": bp.confirmed_at or "",
                "created_at": bp.created_at or _now(),
            }
        )
    return bp


def load_blueprint(repo: Repository, workflow_id: str) -> WorkflowBlueprint | None:
    return blueprint_from_row(repo.get_workflow_blueprint(workflow_id))


def confirm_blueprint(repo: Repository, workflow_id: str) -> WorkflowBlueprint:
    bp = load_blueprint(repo, workflow_id)
    if not bp:
        raise ValueError("工作流蓝图不存在")
    if not bp.product_id and not bp.product_name:
        raise ValueError("请先绑定产品再确认工作流")
    bp.status = "confirmed"
    bp.confirmed_at = _now()
    save_blueprint(repo, bp)
    repo.update_workflow_blueprint(
        workflow_id,
        {"status": "confirmed", "confirmed_at": bp.confirmed_at},
    )
    return bp


def create_blueprint_from_decomposition(
    repo: Repository,
    *,
    decomposition_row: dict[str, Any],
    product_id: str = "",
    product_name: str = "",
    product_specs: str = "",
    selling_points: str = "",
    reference_source: str = "",
    reference_mode: str = "structure_clone",
    platform: str = "tiktok",
    goal: str = "traffic",
    patch: dict[str, Any] | None = None,
) -> WorkflowBlueprint:
    payload = json.loads(decomposition_row.get("payload_json") or "{}")
    bp = blueprint_from_decomposition(
        payload,
        product_id=product_id,
        product_name=product_name,
        product_specs=product_specs,
        selling_points=selling_points,
        reference_source=reference_source or decomposition_row.get("source_url", ""),
        reference_mode=reference_mode,
        decomposition_id=decomposition_row.get("id", ""),
        platform=platform,
        goal=goal,
    )
    if patch:
        merged = bp.model_dump()
        for k, v in patch.items():
            if k in merged and isinstance(v, dict) and isinstance(merged[k], dict):
                merged[k] = {**merged[k], **v}
            else:
                merged[k] = v
        bp = WorkflowBlueprint.model_validate(merged)
    save_blueprint(repo, bp)
    return bp


def get_confirmation_sheet(repo: Repository, workflow_id: str) -> dict[str, Any]:
    bp = load_blueprint(repo, workflow_id)
    if not bp:
        raise ValueError("工作流蓝图不存在")
    return confirmation_sheet(bp)


def require_confirmed_blueprint(repo: Repository, workflow_id: str) -> WorkflowBlueprint:
    if not (workflow_id or "").strip():
        raise ValueError("使用定制工作流时必须提供 workflow_id")
    bp = load_blueprint(repo, workflow_id.strip())
    if not bp:
        raise ValueError(f"工作流蓝图不存在: {workflow_id}")
    if bp.status != "confirmed":
        raise ValueError(
            f"工作流「{workflow_id}」尚未确认。请先向用户展示确认单并调用 confirm 后再创建批次/出片。"
        )
    return bp
