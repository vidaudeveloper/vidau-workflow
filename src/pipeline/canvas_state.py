"""Workflow canvas snapshot for Hermes MCP and embed preview.

Mirrors the web UI node graph (frontend/app.js) but derives status from DB.
"""

from __future__ import annotations

import html
import json
import re
from typing import Any

NODE_IDS = (
    "productInfo",
    "productAssets",
    "benchmark",
    "brief",
    "script",
    "storyboard",
    "render",
    "qa",
)

NODE_LABELS: dict[str, str] = {
    "productInfo": "Input",
    "productAssets": "Product Assets",
    "benchmark": "Benchmark",
    "brief": "Creative Brief",
    "script": "Script",
    "storyboard": "Storyboard",
    "render": "Render",
    "qa": "QA",
}

CANVAS_LAYOUT: dict[str, dict[str, int]] = {
    "productInfo": {"x": 40, "y": 40},
    "productAssets": {"x": 40, "y": 200},
    "benchmark": {"x": 40, "y": 360},
    "brief": {"x": 320, "y": 120},
    "script": {"x": 600, "y": 40},
    "storyboard": {"x": 600, "y": 220},
    "render": {"x": 880, "y": 120},
    "qa": {"x": 1140, "y": 120},
}

CANVAS_EDGES: list[dict[str, str]] = [
    {"from": "productInfo", "to": "brief"},
    {"from": "productAssets", "to": "brief"},
    {"from": "benchmark", "to": "brief"},
    {"from": "brief", "to": "script"},
    {"from": "script", "to": "storyboard"},
    {"from": "storyboard", "to": "render"},
    {"from": "render", "to": "qa"},
]

STATUS_COLORS = {
    "idle": ("#94a3b8", "#f8fafc"),
    "running": ("#2563eb", "#eff6ff"),
    "done": ("#16a34a", "#f0fdf4"),
    "fail": ("#dc2626", "#fef2f2"),
}

NODE_W = 200
NODE_H = 96


def _first_url(text: str) -> str:
    m = re.search(r"https?://\S+", text or "")
    return m.group(0).rstrip(").,]") if m else ""


def _script_node_status(script: dict[str, Any] | None, *, batch_id: str) -> str:
    if not script:
        return "running" if batch_id else "idle"
    rs = script.get("review_status") or ""
    if rs == "失败":
        return "fail"
    if rs == "已通过":
        return "done"
    return "running"


def _prompt_node_status(
    prompts: list[dict[str, Any]], script: dict[str, Any] | None
) -> str:
    if not prompts:
        if script and script.get("review_status") == "已通过":
            return "running"
        return "idle"
    if any(p.get("review_status") == "失败" for p in prompts):
        return "fail"
    if prompts and all(p.get("review_status") == "已通过" for p in prompts):
        return "done"
    return "running"


def _render_node_status(video: dict[str, Any] | None, prompts_ready: bool) -> str:
    if not video:
        return "running" if prompts_ready else "idle"
    url = (video.get("video_url") or "").strip()
    status = (video.get("output_status") or "").strip()
    if status in ("失败", "fail", "error"):
        return "fail"
    if url or status in ("完成", "ok", "done", "成功"):
        return "done"
    return "running"


def _qa_node_status(render_status: str) -> str:
    if render_status == "fail":
        return "fail"
    if render_status == "done":
        return "done"
    if render_status == "running":
        return "running"
    return "idle"


def _node_summary(
    node_id: str,
    *,
    batch: dict[str, Any] | None,
    script: dict[str, Any] | None,
    prompts: list[dict[str, Any]],
    video: dict[str, Any] | None,
    blueprint: dict[str, Any] | None,
) -> str:
    extra = (batch or {}).get("extra_instruction") or ""
    if node_id == "productInfo":
        return (batch or {}).get("product") or _first_url(extra) or "Set product / URL"
    if node_id == "productAssets":
        if blueprint and blueprint.get("product_id"):
            return "Blueprint product linked"
        return "Upload product images" if not (batch or {}).get("product") else "Ready"
    if node_id == "benchmark":
        ref = ""
        if blueprint:
            ref = str((blueprint.get("reference") or {}).get("source_url") or "")
        return ref or _first_url(extra) or "Optional reference video"
    if node_id == "brief":
        brief = extra.strip()
        if blueprint:
            prod = blueprint.get("production") or {}
            creative = blueprint.get("creative") or {}
            if isinstance(creative, dict) and creative.get("brief"):
                brief = str(creative["brief"])
            if isinstance(prod, dict) and prod.get("subtitles"):
                from src.pipeline.production_mode import subtitle_mode_label

                native = bool(prod.get("seedance_native_audio")) or (
                    not prod.get("tts") and prod.get("seedance_native_audio") is not False
                )
                subs = subtitle_mode_label(prod.get("subtitles"), native_audio=native)
                audio = "原生有声" if native else ("TTS" if prod.get("tts") else "默认")
                brief = f"[{audio} · {subs}] " + (brief or "")
        return brief[:120] if brief else "Creative brief / batch instruction"
    if node_id == "script":
        if not script:
            return "Waiting for script"
        return (script.get("hook") or script.get("direction") or script.get("theme") or "Script")[:120]
    if node_id == "storyboard":
        if not prompts:
            return "Waiting for storyboard"
        p0 = prompts[0]
        return (p0.get("prompt_text") or "")[:120]
    if node_id == "render":
        if not video:
            return "Waiting for render"
        if video.get("video_url"):
            return "Preview ready"
        return (video.get("output_status") or "Rendering")[:80]
    if node_id == "qa":
        st = _qa_node_status(_render_node_status(video, bool(prompts)))
        return {"done": "QA passed", "fail": "QA failed", "running": "QA in progress"}.get(
            st, "Waiting for QA"
        )
    return ""


def build_canvas_state(
    repo: Any,
    *,
    batch_id: str = "",
    script_id: str = "",
) -> dict[str, Any]:
    batches = repo.list_batches(admin=True)
    if not batch_id and batches:
        batch_id = batches[0]["id"]
    batch = repo.get_batch(batch_id) if batch_id else None

    scripts = repo.list_scripts(batch_id=batch_id, admin=True) if batch_id else []
    script: dict[str, Any] | None = None
    if script_id:
        script = repo.get_script(script_id)
    elif scripts:
        script = scripts[0]

    prompts: list[dict[str, Any]] = []
    video: dict[str, Any] | None = None
    if script:
        sid = script["id"]
        prompts = [
            p
            for p in repo.list_prompts(admin=True)
            if p.get("script_id") == sid
        ]
        video = repo.get_video_by_script(sid)

    blueprint = None
    wf_id = (batch or {}).get("workflow_id") or ""
    if wf_id:
        blueprint = repo.get_workflow_blueprint(wf_id)

    script_st = _script_node_status(script, batch_id=batch_id or "")
    prompt_st = _prompt_node_status(prompts, script)
    render_st = _render_node_status(video, prompt_st == "done")
    qa_st = _qa_node_status(render_st)

    status_map = {
        "productInfo": "done" if (batch or {}).get("product") else "idle",
        "productAssets": "done" if blueprint or (batch or {}).get("product") else "idle",
        "benchmark": "done" if (blueprint and (blueprint.get("reference") or {}).get("source_url")) or _first_url((batch or {}).get("extra_instruction") or "") else "idle",
        "brief": "done" if (batch or {}).get("extra_instruction") or blueprint else "idle",
        "script": script_st,
        "storyboard": prompt_st,
        "render": render_st,
        "qa": qa_st,
    }

    nodes = []
    for nid in NODE_IDS:
        pos = CANVAS_LAYOUT[nid]
        st = status_map[nid]
        nodes.append(
            {
                "id": nid,
                "label": NODE_LABELS[nid],
                "status": st,
                "summary": _node_summary(
                    nid,
                    batch=batch,
                    script=script,
                    prompts=prompts,
                    video=video,
                    blueprint=blueprint,
                ),
                "x": pos["x"],
                "y": pos["y"],
            }
        )

    return {
        "batch_id": batch_id,
        "script_id": (script or {}).get("id", ""),
        "workflow_id": wf_id,
        "batch_status": (batch or {}).get("status", ""),
        "product": (batch or {}).get("product", ""),
        "direction": (batch or {}).get("direction", ""),
        "nodes": nodes,
        "edges": CANVAS_EDGES,
        "size": {"w": 1460, "h": 760},
    }


def canvas_to_mermaid(state: dict[str, Any]) -> str:
    lines = ["flowchart LR"]
    icon = {"idle": "⏳", "running": "🔄", "done": "✅", "fail": "❌"}
    for n in state.get("nodes") or []:
        nid = n["id"]
        label = n.get("label") or nid
        st = n.get("status") or "idle"
        summary = (n.get("summary") or "").replace('"', "'")[:40]
        lines.append(f'  {nid}["{icon.get(st, "")} {label}<br/>{summary}"]')
    for e in state.get("edges") or []:
        lines.append(f'  {e["from"]} --> {e["to"]}')
    return "\n".join(lines)


def canvas_to_svg(state: dict[str, Any]) -> str:
    w = int((state.get("size") or {}).get("w") or 1460)
    h = int((state.get("size") or {}).get("h") or 760)
    nodes = {n["id"]: n for n in state.get("nodes") or []}

    def port(node_id: str, side: str) -> tuple[float, float]:
        n = nodes[node_id]
        x, y = float(n["x"]), float(n["y"])
        if side == "out":
            return x + NODE_W, y + NODE_H / 2
        return x, y + NODE_H / 2

    paths: list[str] = []
    for e in state.get("edges") or []:
        a = port(e["from"], "out")
        b = port(e["to"], "in")
        mx = (a[0] + b[0]) / 2
        paths.append(
            f'<path d="M{a[0]:.1f},{a[1]:.1f} C{mx:.1f},{a[1]:.1f} {mx:.1f},{b[1]:.1f} {b[0]:.1f},{b[1]:.1f}" '
            f'fill="none" stroke="#94a3b8" stroke-width="2"/>'
        )

    rects: list[str] = []
    for n in state.get("nodes") or []:
        st = n.get("status") or "idle"
        stroke, fill = STATUS_COLORS.get(st, STATUS_COLORS["idle"])
        x, y = float(n["x"]), float(n["y"])
        label = html.escape(n.get("label") or n["id"])
        summary = html.escape((n.get("summary") or "")[:70])
        rects.append(
            f'<g>'
            f'<rect x="{x}" y="{y}" width="{NODE_W}" height="{NODE_H}" rx="10" '
            f'fill="{fill}" stroke="{stroke}" stroke-width="2"/>'
            f'<text x="{x + 12}" y="{y + 22}" font-family="system-ui,sans-serif" '
            f'font-size="13" font-weight="600" fill="#1e293b">{label}</text>'
            f'<text x="{x + 12}" y="{y + 42}" font-family="system-ui,sans-serif" '
            f'font-size="11" fill="#64748b">{st}</text>'
            f'<text x="{x + 12}" y="{y + 62}" font-family="system-ui,sans-serif" '
            f'font-size="10" fill="#475569">{summary}</text>'
            f"</g>"
        )

    title = html.escape(
        f"AdFlow · {state.get('batch_id') or 'no batch'} · {state.get('product') or ''}"
    )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}">'
        f'<rect width="100%" height="100%" fill="#f1f5f9"/>'
        f'<text x="16" y="24" font-family="system-ui,sans-serif" font-size="14" '
        f'font-weight="600" fill="#334155">{title}</text>'
        + "".join(paths)
        + "".join(rects)
        + "</svg>"
    )


def canvas_state_json(state: dict[str, Any]) -> str:
    return json.dumps(state, ensure_ascii=False, indent=2)
