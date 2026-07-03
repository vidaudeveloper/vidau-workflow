"""Per-user Workflow Blueprint — 定制产线配置（替代固定 SOP）。"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


class ReferenceSpec(BaseModel):
    source: str = ""
    mode: str = "structure_clone"  # structure_clone | hook_only | mood_only
    decomposition_id: str = ""
    product_reference_video_url: str = ""
    product_reference_scope: str = "product_only"  # product_only | full (discouraged)
    product_reference_frame_urls: list[str] = Field(default_factory=list)


class VideoSpec(BaseModel):
    duration_sec: int = 15
    aspect_ratio: str = "9:16"
    segment_strategy: str = "single"  # dual | single
    segment_duration_sec: int = 15
    pacing: str = ""
    max_shots: int = 3


class ProductionSpec(BaseModel):
    image_input: str = "product_refs"
    use_first_frame: bool = False
    first_frame_reason: str = ""
    tts: bool = True
    subtitles: str = "burn_in"  # skip | burn_in（原生口播时 burn_in=Whisper 对齐烧录）
    language: str = "英语"
    seedance_native_audio: bool | None = None
    ugc_viral_format: bool | None = None
    prompt_format: str = ""  # viral_15s_blocks | standard | empty=auto
    review_mode: str = "autopilot"  # autopilot | manual


class CreativeSpec(BaseModel):
    hook_style: str = ""
    narrative_template: str = "from_reference"
    narrative_rule: str = ""
    reference_style: str = ""
    scene_style: str = ""
    cta_pattern: str = ""
    lifestyle_notes: str = ""
    creator_persona: dict[str, Any] = Field(default_factory=dict)
    product_visual_truth: dict[str, Any] = Field(default_factory=dict)
    forbidden: list[str] = Field(default_factory=list)
    acceptance_points: list[str] = Field(default_factory=list)
    prompt_profile: str = ""  # default | ugc_15s | ...
    storyboard_profile: str = ""  # default | ugc_viral_15s | ...
    beat_structure: str = ""
    variant_scripts: list[dict[str, Any]] = Field(default_factory=list)


class BatchSpec(BaseModel):
    directions: list[str] = Field(default_factory=list)
    count_per_direction: int = 1
    variant_axis: list[str] = Field(default_factory=list)
    direction_library: str = ""  # relative to repo root, e.g. config/creative/foo.json


class DifficultyAssessment(BaseModel):
    level: str = "中级"  # 低级 | 中级 | 高级
    score: int = 50  # 0-100
    reasoning: str = ""
    recommended_first_frame: bool = False
    first_frame_reason: str = ""


class WorkflowBlueprint(BaseModel):
    workflow_id: str = ""
    platform: str = "tiktok"
    goal: str = "traffic"  # traffic | conversion | awareness
    product_id: str = ""
    product_name: str = ""
    status: str = "draft"  # draft | confirmed
    reference: ReferenceSpec = Field(default_factory=ReferenceSpec)
    video_spec: VideoSpec = Field(default_factory=VideoSpec)
    production: ProductionSpec = Field(default_factory=ProductionSpec)
    creative: CreativeSpec = Field(default_factory=CreativeSpec)
    batch: BatchSpec = Field(default_factory=BatchSpec)
    difficulty: DifficultyAssessment = Field(default_factory=DifficultyAssessment)
    estimate: dict[str, Any] = Field(default_factory=dict)
    confirmed_at: str = ""
    created_at: str = ""
    updated_at: str = ""

    def ensure_id(self) -> str:
        if not self.workflow_id:
            self.workflow_id = f"wf_{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:6]}"
        return self.workflow_id

    def to_storage(self) -> dict[str, Any]:
        self.ensure_id()
        now = datetime.now(timezone.utc).isoformat()
        if not self.created_at:
            self.created_at = now
        self.updated_at = now
        return self.model_dump()

    @classmethod
    def from_storage(cls, raw: dict[str, Any] | str | None) -> WorkflowBlueprint | None:
        if not raw:
            return None
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except json.JSONDecodeError:
                return None
        if not isinstance(raw, dict):
            return None
        return cls.model_validate(raw)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def assess_product_difficulty(
    *,
    product_specs: str = "",
    selling_points: str = "",
) -> DifficultyAssessment:
    text = f"{product_specs}\n{selling_points}".lower()
    score = 35
    reasons: list[str] = []

    interaction_markers = (
        "按键", "按钮", "屏幕", "lcd", "display", "interface", "交互",
        "演示", "安装", "配件", "模块", "组合", "套装", "kit",
    )
    simple_markers = ("单机", "整机", "外观", "compact", "portable", "static")

    for m in interaction_markers:
        if m in text:
            score += 8
            reasons.append(f"含交互/配件要素「{m}」")
    for m in simple_markers:
        if m in text:
            score -= 3

    if re.search(r"\d+\s*(个|件|种|款|pcs|pieces)", text):
        score += 10
        reasons.append("多配件/多 SKU")

    score = max(0, min(100, score))
    if score < 40:
        level = "低级"
        rec_ff = False
        ff_reason = "产品外观简单，参考图直出即可定构图"
    elif score < 65:
        level = "中级"
        rec_ff = True
        ff_reason = "建议生成首帧图以固定按键/屏幕构图与场景"
    else:
        level = "高级"
        rec_ff = True
        ff_reason = "产品复杂或交互多，强烈建议首帧 + 试拍 1 条再批量"

    return DifficultyAssessment(
        level=level,
        score=score,
        reasoning="；".join(reasons) if reasons else "基于规格文本的默认评估",
        recommended_first_frame=rec_ff,
        first_frame_reason=ff_reason,
    )


def blueprint_from_decomposition(
    decomp: dict[str, Any],
    *,
    product_id: str = "",
    product_name: str = "",
    product_specs: str = "",
    selling_points: str = "",
    reference_source: str = "",
    reference_mode: str = "structure_clone",
    decomposition_id: str = "",
    platform: str = "tiktok",
    goal: str = "traffic",
) -> WorkflowBlueprint:
    duration = int(decomp.get("recommended_duration_sec") or decomp.get("duration_sec") or 15)
    seg_strategy = str(decomp.get("recommended_segment_strategy") or "").strip().lower()
    if not seg_strategy:
        seg_strategy = "single" if duration <= 18 else "dual"
    seg_dur = int(decomp.get("recommended_segment_duration_sec") or 15)
    if seg_strategy == "single":
        seg_dur = min(duration, 30)

    difficulty = assess_product_difficulty(
        product_specs=product_specs,
        selling_points=selling_points,
    )

    ref_style = str(decomp.get("reference_style_summary") or "").strip()
    narrative = str(decomp.get("narrative_rule") or "").strip()
    hook = str(decomp.get("hook_type") or "").strip()

    forbidden = list(decomp.get("not_recommended_to_clone") or [])
    acceptance = list(decomp.get("reusable_for_clone") or [])[:6]
    creator = decomp.get("creator_persona") or {}
    if not isinstance(creator, dict):
        creator = {}
    pv_truth = decomp.get("product_visual_truth") or {}
    if not isinstance(pv_truth, dict):
        pv_truth = {}
    cta_pat = str(decomp.get("cta_pattern") or "").strip()
    lifestyle = str(decomp.get("lifestyle_notes") or "").strip()
    if pv_truth.get("hero_shots"):
        acceptance = list(acceptance) + [f"必拍: {x}" for x in pv_truth.get("hero_shots", [])[:4]]
    if pv_truth.get("do_not_copy_from_video"):
        forbidden = list(forbidden) + list(pv_truth.get("do_not_copy_from_video", []))

    prod_tts = True
    prod_subs = "burn_in"
    prod_native: bool | None = None
    prod_viral: bool | None = None
    prod_prompt_fmt = ""
    audio_mode = str(decomp.get("audio_mode") or decomp.get("recommended_audio_mode") or "").lower()
    if audio_mode in ("native", "seedance_native", "seedance_native_audio"):
        prod_tts = False
        prod_subs = "skip"
        prod_native = True
    if str(decomp.get("prompt_format") or "").strip():
        prod_prompt_fmt = str(decomp.get("prompt_format")).strip()
    if decomp.get("ugc_viral_format") is True:
        prod_viral = True

    bp = WorkflowBlueprint(
        platform=platform,
        goal=goal,
        product_id=product_id,
        product_name=product_name,
        reference=ReferenceSpec(
            source=reference_source,
            mode=reference_mode,
            decomposition_id=decomposition_id,
        ),
        video_spec=VideoSpec(
            duration_sec=duration,
            aspect_ratio=str(decomp.get("aspect_ratio") or "9:16"),
            segment_strategy=seg_strategy,
            segment_duration_sec=seg_dur,
            pacing=str(decomp.get("pacing") or ""),
            max_shots=int(decomp.get("shot_count_estimate") or 3),
        ),
        production=ProductionSpec(
            use_first_frame=difficulty.recommended_first_frame,
            first_frame_reason=difficulty.first_frame_reason,
            tts=prod_tts,
            subtitles=prod_subs,
            language=str(decomp.get("language") or "英语"),
            seedance_native_audio=prod_native,
            ugc_viral_format=prod_viral,
            prompt_format=prod_prompt_fmt,
        ),
        creative=CreativeSpec(
            hook_style=hook,
            narrative_template="from_reference",
            narrative_rule=narrative,
            reference_style=ref_style,
            cta_pattern=cta_pat,
            lifestyle_notes=lifestyle,
            creator_persona=creator,
            product_visual_truth=pv_truth,
            forbidden=forbidden,
            acceptance_points=acceptance,
            beat_structure=str(decomp.get("beat_structure") or "").strip(),
            storyboard_profile=str(decomp.get("storyboard_profile") or "").strip(),
            prompt_profile=str(decomp.get("prompt_profile") or "").strip(),
        ),
        difficulty=difficulty,
        batch=BatchSpec(count_per_direction=1),
    )
    bp.ensure_id()
    return bp


def build_production_context(bp: WorkflowBlueprint) -> str:
    """注入脚本/分镜 LLM 的蓝图上下文（替代写死 SOP）。"""
    vs = bp.video_spec
    prod = bp.production
    lines = [
        "--- Workflow Blueprint（用户已确认的生产方案）---",
        f"平台: {bp.platform} | 目标: {bp.goal}",
        f"成片时长: {vs.duration_sec}s | 比例: {vs.aspect_ratio}",
        f"出片策略: {vs.segment_strategy}（段长 {vs.segment_duration_sec}s）",
        f"节奏: {vs.pacing or '见对标'} | 最多分镜: {vs.max_shots}",
        f"音频策略: tts={prod.tts}, subtitles={prod.subtitles}"
        + (
            f", seedance_native_audio={prod.seedance_native_audio}"
            if prod.seedance_native_audio is not None
            else ""
        )
        + (
            f", ugc_viral_format={prod.ugc_viral_format}"
            if prod.ugc_viral_format is not None
            else ""
        ),
    ]
    if prod.prompt_format:
        lines.append(f"Prompt 格式: {prod.prompt_format}")
    if bp.creative.prompt_profile:
        lines.append(f"脚本 prompt_profile: {bp.creative.prompt_profile}")
    if bp.creative.storyboard_profile:
        lines.append(f"分镜 storyboard_profile: {bp.creative.storyboard_profile}")
    if bp.creative.beat_structure:
        lines.append(f"节拍结构:\n{bp.creative.beat_structure}")
    if bp.creative.reference_style:
        lines.append(f"对标风格:\n{bp.creative.reference_style}")
    if bp.creative.narrative_rule:
        lines.append(f"叙事结构:\n{bp.creative.narrative_rule}")
    if bp.creative.scene_style:
        lines.append(f"场景风格: {bp.creative.scene_style}")
    if bp.creative.hook_style:
        lines.append(f"钩子类型: {bp.creative.hook_style}")
    cp = bp.creative.creator_persona or {}
    if cp:
        cp_lines = [f"{k}: {v}" for k, v in cp.items() if v]
        lines.append("达人形象（必须有记忆点）:\n" + "\n".join(cp_lines))
    pv = bp.creative.product_visual_truth or {}
    if pv:
        pv_lines = [f"{k}: {v}" for k, v in pv.items() if v and k != "hero_shots"]
        heroes = pv.get("hero_shots") or []
        if heroes:
            pv_lines.append("必拍镜头: " + "; ".join(heroes))
        lines.append("产品实拍真相（视频生成以此为准）:\n" + "\n".join(pv_lines))
    if bp.creative.cta_pattern:
        lines.append(
            f"结尾购买引导（画面仅图标+产品，文案走口播/后期字幕）:\n{bp.creative.cta_pattern}"
        )
    lines.append(
        "画面图形约束: 生成时禁止可读字幕/花字；允许箭头、星星、无字贴纸；"
        + (
            "Seedance 原生有声，无后期字幕烧录。"
            if prod.seedance_native_audio
            or (not prod.tts and (prod.subtitles or "").strip().lower() == "skip")
            else "字幕由后期烧录（若 production.tts=true）。"
        )
    )
    if bp.batch.direction_library:
        lines.append(f"变体方向库: {bp.batch.direction_library}")
    if bp.creative.lifestyle_notes:
        lines.append(f"生活化场景:\n{bp.creative.lifestyle_notes}")
    if bp.creative.forbidden:
        lines.append("禁止复刻/禁止出现:\n" + "\n".join(f"- {x}" for x in bp.creative.forbidden))
    if bp.creative.acceptance_points:
        lines.append("验收要点:\n" + "\n".join(f"- {x}" for x in bp.creative.acceptance_points))
    if bp.reference.source:
        lines.append(f"参考视频: {bp.reference.source}（模式: {bp.reference.mode}）")
    lines.append(
        f"首帧图: {'是' if bp.production.use_first_frame else '否'}"
        + (f" — {bp.production.first_frame_reason}" if bp.production.first_frame_reason else "")
    )
    if bp.reference.product_reference_video_url:
        lines.append(
            "产品参考视频（Seedance reference_video，仅学撕开/粉末/包装，禁止复刻人物剧情）: "
            + bp.reference.product_reference_video_url
        )
    if vs.segment_strategy == "single" and vs.duration_sec <= 15:
        lines.append(
            "【15s 单段硬性约束】时间轴必须 0–15s（单镜或最多 3 镜）；"
            "禁止 30s 双段结构（无 Part A/B、无 15–30s 时间窗）；"
            "口播 38–52 英文词（约 12–15s TTS）；最多 2–3 个卖点。"
        )
    if prod.review_mode == "autopilot":
        lines.append(
            "审核模式: autopilot — 脚本与分镜 Prompt 自动批准，无需人工闸门。"
        )
    return "\n".join(lines)


def confirmation_sheet(bp: WorkflowBlueprint) -> dict[str, Any]:
    """生产确认单 — Agent 展示给用户逐项确认。"""
    from src.pipeline.production_mode import (
        production_subtitle_options,
        subtitle_mode_label,
        use_native_seedance,
    )

    vs = bp.video_spec
    prod = bp.production
    native = use_native_seedance(blueprint=bp)
    seg_desc = (
        f"单段 {vs.duration_sec}s 直出"
        if vs.segment_strategy == "single"
        else f"{vs.duration_sec}s（约 2×{vs.segment_duration_sec}s 拼接）"
    )
    return {
        "workflow_id": bp.workflow_id,
        "status": bp.status,
        "sections": {
            "成片规格": {
                "时长": f"{vs.duration_sec}s",
                "比例": vs.aspect_ratio,
                "结构": seg_desc,
                "节奏": vs.pacing or "（来自对标拆解）",
                "最大分镜数": vs.max_shots,
            },
            "产品": {
                "产品": bp.product_name or bp.product_id or "（待绑定）",
                "难度": f"{bp.difficulty.level}（{bp.difficulty.score}/100）",
                "难度说明": bp.difficulty.reasoning,
            },
            "出片策略": {
                "图片输入": prod.image_input,
                "生成首帧图": prod.use_first_frame,
                "首帧原因": prod.first_frame_reason or bp.difficulty.first_frame_reason,
                "TTS 口播": prod.tts,
                "字幕": prod.subtitles,
                "字幕方案": subtitle_mode_label(prod.subtitles, native_audio=native),
                "可选字幕方案": production_subtitle_options(native_audio=native),
                "语言": prod.language,
                "Seedance 原生有声": prod.seedance_native_audio,
                "Viral 三段式": prod.ugc_viral_format,
                "Prompt 格式": prod.prompt_format or "（自动）",
                "审核模式": prod.review_mode,
                "审核说明": (
                    "autopilot = 确认后全自动，无脚本/分镜人工闸门"
                    if prod.review_mode == "autopilot"
                    else "manual = 脚本与分镜 Prompt 需人工审核"
                ),
            },
            "创意约束": {
                "对标模式": bp.reference.mode,
                "参考来源": bp.reference.source or "（无）",
                "钩子风格": bp.creative.hook_style or "（来自对标）",
                "场景": bp.creative.scene_style or "（待补充）",
                "禁止项": bp.creative.forbidden,
                "验收点": bp.creative.acceptance_points,
            },
            "达人形象": {
                k: v
                for k, v in (bp.creative.creator_persona or {}).items()
                if v
            }
            or {"说明": "（未从对标学习，建议补充穿搭/美甲/记忆点）"},
            "产品实拍真相": {
                **{
                    k: v
                    for k, v in (bp.creative.product_visual_truth or {}).items()
                    if v and k != "hero_shots"
                },
                **(
                    {"必拍镜头": bp.creative.product_visual_truth.get("hero_shots")}
                    if (bp.creative.product_visual_truth or {}).get("hero_shots")
                    else {}
                ),
            }
            or {"说明": "（未绑定产品实拍，粉末/包装可能与视频不符）"},
            "结尾购买引导": bp.creative.cta_pattern or "（待补充）",
            "批量": {
                "方向": bp.batch.directions or ["（创建批次时指定）"],
                "每方向条数": bp.batch.count_per_direction,
            },
        },
        "estimate": bp.estimate,
        "requires_confirmation_before_spend": bp.status != "confirmed",
    }


def merge_batch_overrides(
    bp: WorkflowBlueprint,
    *,
    direction: str = "",
    count: int = 0,
    extra_instruction: str = "",
) -> WorkflowBlueprint:
    """创建批次时合并对话级覆盖（方向/条数/补充指令），核心规格仍以蓝图为准。"""
    out = bp.model_copy(deep=True)
    if direction:
        if direction not in out.batch.directions:
            out.batch.directions = [direction] + list(out.batch.directions)
    if count > 0:
        out.batch.count_per_direction = count
    note = extra_instruction.strip()
    if note and note not in out.creative.acceptance_points:
        out.creative.acceptance_points = list(out.creative.acceptance_points) + [note]
    return out
