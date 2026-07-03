import asyncio
import json
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.config import get_settings
from src.db.repository import Repository
from src.pipeline.brand_profile import BrandProfile, brand_from_product, brand_from_spec_json
from src.pipeline.llm import LLMService
from src.pipeline.product_conversion import (
    build_conversion_context,
    pricing_context_for_product,
    resolve_conversion_method,
)
from src.pipeline.script_normalize import normalize_script_data, normalize_shots
from src.pipeline.seedance_prompt_compile import resolve_segment_prompt
from src.pipeline.subtitles import burn_subtitles_on_video, resolve_burn_input_path
from src.pipeline.tts_post import apply_tts_post_production
from src.pipeline.video import VideoService
from src.pipeline.video_concat import concat_remote_videos, download_remote_video
from src.pipeline.voice_persona import build_voice_profile, resolve_tts_voice, voice_hint_for_seedance
from src.pipeline.production_mode import (
    normalize_subtitles,
    production_mode_summary,
    should_burn_subtitles,
    subtitle_mode_label,
    seedance_visual_only,
    use_native_seedance_15s,
    use_ugc_viral_prompt_format,
)
from src.pipeline.ugc_directions import (
    effective_direction_library,
    format_direction_block,
    should_inject_variant_direction,
)
from src.pipeline.workflow_language import is_spanish
from src.pipeline.workflow_blueprint import (
    WorkflowBlueprint,
    build_production_context,
    merge_batch_overrides,
)
from src.pipeline.workflow_service import load_blueprint, require_confirmed_blueprint
from src.pipeline.kit_components import (
    append_kit_negative,
    build_kit_constraint,
    merge_kit_into_product_understanding,
)
from src.pipeline.voiceover_budget import (
    annotate_voiceover_spec,
    count_script_audio_words,
    estimate_tts_seconds,
    voiceover_budget_hint,
)
from src.pipeline.voiceover_fallback import ensure_storyboard_voiceover, resolve_voiceover_tracks
from src.uploads import parse_product_image_urls


def _max_shot_end_sec(shots: list[dict[str, Any]]) -> float:
    max_end = 0.0
    for shot in shots:
        for part in re.findall(r"(\d+(?:\.\d+)?)", str(shot.get("time") or "")):
            max_end = max(max_end, float(part))
    return max_end


class WorkflowOrchestrator:
    """批次生成 → 脚本审核 → 分镜 Prompt → 视频产出 全流程编排。"""

    def __init__(self, repo: Repository | None = None):
        self.settings = get_settings()
        self.repo = repo or Repository()
        self._llm: LLMService | None = None
        self._video: VideoService | None = None

    @property
    def llm(self) -> LLMService:
        if self._llm is None:
            self._llm = LLMService(self.settings)
        return self._llm

    @property
    def video(self) -> VideoService:
        if self._video is None:
            self._video = VideoService(self.settings)
        return self._video

    def _use_platform_video(self) -> bool:
        if (self.settings.video_provider or "").lower() == "platform":
            return True
        return (self.settings.aigc_billing_mode or "none").lower() == "platform"

    def _video_engine_label(self) -> str:
        return "主站 AI Video" if self._use_platform_video() else "Seedance 2.0"

    def _store_platform_token(self, video_id: str, platform_token: str) -> None:
        if not platform_token.strip():
            return
        seg = self._read_segment_json(video_id)
        if seg.get("platform_token") == platform_token:
            return
        seg["platform_token"] = platform_token
        self.repo.update_video(
            video_id, {"segment_urls_json": json.dumps(seg, ensure_ascii=False)}
        )

    def _platform_token_for_video(self, video_id: str, platform_token: str = "") -> str:
        if platform_token.strip():
            return platform_token.strip()
        return (self._read_segment_json(video_id).get("platform_token") or "").strip()

    @staticmethod
    def _billing_biz_no(video_id: str, segment: str) -> str:
        return f"{video_id}_{segment}"

    def _store_segment_charge(
        self, video_id: str, segment: str, charge: dict[str, Any]
    ) -> None:
        if not charge:
            return
        seg = self._read_segment_json(video_id)
        charges = seg.get("charges") if isinstance(seg.get("charges"), dict) else {}
        charges[segment] = charge
        seg["charges"] = charges
        self.repo.update_video(
            video_id, {"segment_urls_json": json.dumps(seg, ensure_ascii=False)}
        )

    def _segment_charge(self, video_id: str, segment: str) -> dict[str, Any]:
        charges = self._read_segment_json(video_id).get("charges") or {}
        if isinstance(charges, dict):
            item = charges.get(segment)
            return item if isinstance(item, dict) else {}
        return {}

    def _blueprint_for_batch_id(self, batch_id: str) -> WorkflowBlueprint | None:
        batch = self.repo.get_batch(batch_id)
        if not batch:
            return None
        wid = (batch.get("workflow_id") or "").strip()
        if not wid:
            return None
        return load_blueprint(self.repo, wid)

    def _blueprint_for_script(self, script: dict[str, Any]) -> WorkflowBlueprint | None:
        return self._blueprint_for_batch_id(str(script.get("batch_id") or ""))

    def prepare_batch(
        self,
        *,
        product: str,
        direction: str,
        count: int = 3,
        extra_instruction: str = "",
        creator: str = "",
        difficulty_level: str = "低级",
        language: str = "英语",
        owner_user_id: str = "",
        use_first_frame: bool = False,
        workflow_id: str = "",
    ) -> str:
        """校验并创建批次记录，立即返回 batch_id（脚本在后台生成）。"""
        bp: WorkflowBlueprint | None = None
        if (workflow_id or "").strip():
            bp = require_confirmed_blueprint(self.repo, workflow_id.strip())

        prod_obj = self.repo.get_product(product)
        if not prod_obj:
            raise ValueError("所选产品不存在，请刷新页面后重试")
        if not parse_product_image_urls(prod_obj):
            raise ValueError(
                f"产品「{prod_obj['name']}」未上传产品图，请先在「固定配置 → 产品」中上传 1-9 张图片后再创建批次"
            )
        if not (prod_obj.get("product_specs") or "").strip():
            raise ValueError(
                f"产品「{prod_obj['name']}」缺少外观与交互说明，请先在「固定配置 → 产品」中 AI 识别并确认"
            )
        if not int(prod_obj.get("product_specs_confirmed") or 0):
            raise ValueError(
                f"产品「{prod_obj['name']}」的外观说明尚未人工确认，请先在「固定配置 → 产品」中确认后再创建批次"
            )
        dir_obj = self.repo.get_direction(direction)
        if bp:
            bp = merge_batch_overrides(
                bp,
                direction=dir_obj["name"] if dir_obj else direction,
                count=count,
                extra_instruction=extra_instruction,
            )
            difficulty_level = bp.difficulty.level or difficulty_level
            use_first_frame = bool(bp.production.use_first_frame)
            language = bp.production.language or language
            blueprint_ctx = build_production_context(bp)
            extra_instruction = (
                f"{blueprint_ctx}\n\n{extra_instruction}".strip()
                if extra_instruction.strip()
                else blueprint_ctx
            )
        batch_id = f"B{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}"
        self.repo.create_batch(
            {
                "id": batch_id,
                "product": prod_obj["name"],
                "direction": dir_obj["name"] if dir_obj else direction,
                "count": count,
                "extra_instruction": extra_instruction,
                "creator": creator,
                "status": "生成中",
                "difficulty_level": difficulty_level,
                "language": language,
                "owner_user_id": owner_user_id,
                "use_first_frame": int(bool(use_first_frame)),
                "workflow_id": bp.workflow_id if bp else (workflow_id.strip() if workflow_id else ""),
            }
        )
        return batch_id

    async def run_batch_scripts(
        self,
        batch_id: str,
        *,
        product: str,
        direction: str,
        count: int,
        extra_instruction: str = "",
        difficulty_level: str = "低级",
        account_id: str = "",
        language: str = "英语",
        producer: str = "",
        use_first_frame: bool = False,
    ) -> None:
        prod_obj = self.repo.get_product(product)
        dir_obj = self.repo.get_direction(direction)
        product_name = prod_obj["name"] if prod_obj else product
        direction_name = dir_obj["name"] if dir_obj else direction
        direction_desc = dir_obj["description"] if dir_obj else ""
        try:
            await self.generate_scripts_for_batch(
                batch_id,
                product_name,
                direction_name,
                count,
                extra_instruction,
                selling_points=prod_obj["selling_points"] if prod_obj else "",
                product_specs=prod_obj.get("product_specs", "") if prod_obj else "",
                direction_description=direction_desc,
                product_obj=prod_obj,
                difficulty_level=difficulty_level,
                account_id=account_id,
                language=language,
                producer=producer,
                use_first_frame=use_first_frame,
            )
            self.repo.update_batch_status(batch_id, "待脚本审核")
        except Exception:  # noqa: BLE001
            self.repo.update_batch_status(batch_id, "生成失败")
            raise

    def begin_batch_retry(self, batch_id: str) -> None:
        batch = self.repo.get_batch(batch_id)
        if not batch:
            raise ValueError("批次不存在")
        if batch.get("status") == "生成中":
            raise ValueError("批次正在生成中，请稍候")
        self.repo.delete_scripts_for_batch(batch_id)
        self.repo.update_batch_status(batch_id, "生成中")

    async def retry_batch_scripts(self, batch_id: str) -> None:
        batch = self.repo.get_batch(batch_id)
        if not batch:
            return
        await self.run_batch_scripts(
            batch_id,
            product=batch["product"],
            direction=batch["direction"],
            count=int(batch["count"]),
            extra_instruction=batch.get("extra_instruction", ""),
            difficulty_level=batch.get("difficulty_level", "低级"),
            language=batch.get("language", "英语"),
            use_first_frame=bool(int(batch.get("use_first_frame", 0) or 0)),
        )

    def delete_failed_batch(self, batch_id: str) -> None:
        batch = self.repo.get_batch(batch_id)
        if not batch:
            raise ValueError("批次不存在")
        if batch.get("status") != "生成失败":
            raise ValueError("仅可删除状态为「生成失败」的批次")
        self.repo.delete_batch_cascade(batch_id)

    async def recover_stuck_batches(self) -> None:
        """将无脚本或已全部失败的僵尸批次标为生成失败。"""
        for batch in self.repo.list_batches():
            if batch.get("status") != "生成中":
                continue
            scripts = self.repo.list_scripts(batch_id=batch["id"])
            if not scripts:
                self.repo.update_batch_status(batch["id"], "生成失败")
            elif all(s.get("review_status") == "失败" for s in scripts):
                self.repo.update_batch_status(batch["id"], "生成失败")

    async def create_batch(
        self,
        *,
        product: str,
        direction: str,
        count: int = 3,
        extra_instruction: str = "",
        creator: str = "",
        difficulty_level: str = "低级",
        account_id: str = "",
        language: str = "英语",
        producer: str = "",
        use_first_frame: bool = False,
    ) -> str:
        batch_id = self.prepare_batch(
            product=product,
            direction=direction,
            count=count,
            extra_instruction=extra_instruction,
            creator=creator,
            difficulty_level=difficulty_level,
            language=language,
            use_first_frame=use_first_frame,
        )
        await self.run_batch_scripts(
            batch_id,
            product=product,
            direction=direction,
            count=count,
            extra_instruction=extra_instruction,
            difficulty_level=difficulty_level,
            account_id=account_id,
            language=language,
            producer=producer,
            use_first_frame=use_first_frame,
        )
        return batch_id

    def _finalize_autopilot_batch_status(self, batch_id: str) -> None:
        scripts = self.repo.list_scripts(batch_id=batch_id)
        videos = [self.repo.get_video_by_script(s["id"]) for s in scripts]
        videos = [v for v in videos if v]
        if not videos:
            self.repo.update_batch_status(batch_id, "生成失败")
            return
        statuses = [v.get("output_status") or "" for v in videos]
        if all(s == "待交付" for s in statuses):
            self.repo.update_batch_status(batch_id, "全流程完成")
        elif any(s in ("生成中", "排队中") for s in statuses):
            self.repo.update_batch_status(batch_id, "视频生成中")
        elif any(s == "失败" for s in statuses):
            self.repo.update_batch_status(batch_id, "部分失败")
        else:
            self.repo.update_batch_status(batch_id, "视频生成中")

    async def run_full_autopilot(
        self,
        batch_id: str,
        *,
        product: str,
        direction: str,
        count: int,
        extra_instruction: str = "",
        difficulty_level: str = "低级",
        account_id: str = "",
        language: str = "英语",
        producer: str = "",
        reviewer: str = "自动审核",
        use_first_frame: bool = False,
        platform_token: str = "",
    ) -> None:
        """脚本生成 → 自动通过审核 → Prompt → 自动通过 → 出片（后台长任务）。"""
        try:
            await self.run_batch_scripts(
                batch_id,
                product=product,
                direction=direction,
                count=count,
                extra_instruction=extra_instruction,
                difficulty_level=difficulty_level,
                account_id=account_id,
                language=language,
                producer=producer,
                use_first_frame=use_first_frame,
            )
            scripts = self.repo.list_scripts(batch_id=batch_id)
            if any(s.get("review_status") == "失败" for s in scripts):
                self.repo.update_batch_status(batch_id, "生成失败")
                return
            if not scripts:
                self.repo.update_batch_status(batch_id, "生成失败")
                return

            self.repo.update_batch_status(batch_id, "自动审核中")
            pending_scripts = [s for s in scripts if s.get("review_status") == "待审核"]
            for script in pending_scripts:
                await self.review_script(
                    script["id"],
                    status="通过",
                    note="一键全流程自动通过",
                    reviewer=reviewer,
                )

            scripts = self.repo.list_scripts(batch_id=batch_id)
            prompt_ids: list[str] = []
            for script in scripts:
                prompt = self.repo.get_prompt_by_script(script["id"])
                if prompt and prompt.get("review_status") == "待审核":
                    self.begin_prompt_review(prompt["id"], status="通过")
                    prompt_ids.append(prompt["id"])

            if not prompt_ids:
                self.repo.update_batch_status(batch_id, "生成失败")
                return

            self.repo.update_batch_status(batch_id, "视频生成中")
            await asyncio.gather(
                *(
                    self.complete_prompt_review(
                        pid,
                        status="通过",
                        note="一键全流程自动通过",
                        platform_token=platform_token,
                    )
                    for pid in prompt_ids
                ),
                return_exceptions=True,
            )
            self._finalize_autopilot_batch_status(batch_id)
        except Exception:  # noqa: BLE001
            self.repo.update_batch_status(batch_id, "生成失败")
            raise

    def copy_script_branch(
        self,
        parent_script_id: str,
        *,
        hook: str | None = None,
        direction: str | None = None,
        branch_node: str = "script",
    ) -> str:
        """复制脚本为分支版本（保留父版本，仅从分镜/出片重跑）。"""
        parent = self.repo.get_script(parent_script_id)
        if not parent:
            raise ValueError(f"脚本不存在: {parent_script_id}")
        new_id = f"{parent_script_id}-b{uuid.uuid4().hex[:4]}"
        note = f"branch:{parent_script_id}:{branch_node}"
        self.repo.create_script(
            {
                "id": new_id,
                "batch_id": parent["batch_id"],
                "product": parent.get("product", ""),
                "direction": direction if direction is not None else parent.get("direction", ""),
                "theme": parent.get("theme", ""),
                "hook": hook if hook is not None else parent.get("hook", ""),
                "outline": parent.get("outline", ""),
                "cta": parent.get("cta", ""),
                "shots": parent.get("shots", []),
                "review_status": "已通过",
                "review_note": note,
                "reviewer": "分支",
                "flow_status": "Prompt生成中",
                "difficulty_level": parent.get("difficulty_level", "低级"),
                "account_id": parent.get("account_id", ""),
                "language": parent.get("language", "英语"),
                "producer": parent.get("producer", ""),
                "use_first_frame": parent.get("use_first_frame", 0),
            }
        )
        return new_id

    def copy_prompt_branch(self, parent_script_id: str, child_script_id: str) -> str:
        """将父脚本分镜复制到分支脚本（用于仅重跑出片）。"""
        parent_prompt = self.repo.get_prompt_by_script(parent_script_id)
        if not parent_prompt:
            raise ValueError("父版本尚无分镜，无法复制")
        prompt_id = f"P{child_script_id}"
        self.repo.create_prompt(
            {
                "id": prompt_id,
                "script_id": child_script_id,
                "output_mode": parent_prompt.get("output_mode", "AI直出"),
                "prompt_text": parent_prompt.get("prompt_text", ""),
                "prompt_part_b": parent_prompt.get("prompt_part_b", ""),
                "product_spec_json": parent_prompt.get("product_spec_json", ""),
                "negative_prompt": parent_prompt.get("negative_prompt", ""),
                "duration_sec": parent_prompt.get("duration_sec", 30),
                "segment_duration_sec": parent_prompt.get("segment_duration_sec", 15),
                "aspect_ratio": parent_prompt.get("aspect_ratio", "9:16"),
                "review_status": "已通过",
                "review_note": f"branch_prompt:{parent_script_id}",
                "flow_status": "出片中",
            }
        )
        return prompt_id

    async def run_from_storyboard(
        self,
        script_id: str,
        *,
        platform_token: str = "",
        storyboard_note: str = "",
    ) -> None:
        """从分镜节点重跑：脚本保留，重新生成分镜并出片。"""
        script = self.repo.get_script(script_id)
        if not script:
            return
        self.repo.delete_script_downstream(script_id)
        self.repo.update_script(
            script_id,
            {"review_status": "已通过", "flow_status": "Prompt生成中", "review_note": script.get("review_note", "")},
        )
        await self._create_prompt_from_script(script)
        prompt = self.repo.get_prompt_by_script(script_id)
        if not prompt:
            return
        if storyboard_note.strip():
            self.begin_prompt_review(prompt["id"], status="不通过-调Prompt")
            await self.complete_prompt_review(
                prompt["id"],
                status="不通过-调Prompt",
                note=storyboard_note.strip(),
                platform_token="",
            )
            prompt = self.repo.get_prompt_by_script(script_id)
            if not prompt:
                return
        self.begin_prompt_review(prompt["id"], status="通过")
        await self.complete_prompt_review(
            prompt["id"],
            status="通过",
            note="分支/重跑自动通过",
            platform_token=platform_token,
        )

    async def regenerate_storyboard_and_video(
        self,
        script_id: str,
        *,
        platform_token: str = "",
        storyboard_note: str = "",
    ) -> None:
        """在现有脚本上重调分镜并重新出片。"""
        prompt = self.repo.get_prompt_by_script(script_id)
        if not prompt:
            await self.run_from_storyboard(
                script_id,
                platform_token=platform_token,
                storyboard_note=storyboard_note,
            )
            return
        self.repo.delete_script_downstream(script_id)
        script = self.repo.get_script(script_id)
        if not script:
            return
        await self._create_prompt_from_script(script)
        prompt = self.repo.get_prompt_by_script(script_id)
        if not prompt:
            return
        if storyboard_note.strip():
            self.begin_prompt_review(prompt["id"], status="不通过-调Prompt")
            await self.complete_prompt_review(
                prompt["id"],
                status="不通过-调Prompt",
                note=storyboard_note.strip(),
                platform_token="",
            )
            prompt = self.repo.get_prompt_by_script(script_id)
            if not prompt:
                return
        self.begin_prompt_review(prompt["id"], status="通过")
        await self.complete_prompt_review(
            prompt["id"],
            status="通过",
            note="分镜重生成自动通过",
            platform_token=platform_token,
        )

    async def rerun_video_for_script(self, script_id: str, *, platform_token: str = "") -> None:
        """仅重跑出片（分镜不变）。"""
        prompt = self.repo.get_prompt_by_script(script_id)
        if not prompt:
            raise ValueError("需要先有分镜才能重跑出片")
        video_id = f"V{prompt['id']}"
        existing = self.repo.get_video(video_id)
        reset = {
            "output_status": "生成中",
            "fail_reason": "",
            "note": "分支重跑出片中…",
            "video_url": "",
            "segment_urls_json": "",
            "subtitle_status": "未开始",
        }
        if existing:
            self.repo.update_video(video_id, reset)
        else:
            self.repo.create_video(
                {
                    "id": video_id,
                    "prompt_id": prompt["id"],
                    "script_id": script_id,
                    "output_mode": "AI直出",
                    **reset,
                }
            )
        if platform_token.strip():
            self._store_platform_token(video_id, platform_token)
        await self._generate_ai_video(prompt, video_id, platform_token=platform_token)

    async def toc_branch_pipeline(
        self,
        source_script_id: str,
        *,
        target_script_id: str,
        node: str,
        note: str = "",
        platform_token: str = "",
    ) -> None:
        """To C 分支：在 target 脚本上从指定节点重跑（target 可为新分支或当前版本）。"""
        if node == "video":
            if (
                target_script_id != source_script_id
                and not self.repo.get_prompt_by_script(target_script_id)
            ):
                self.copy_prompt_branch(source_script_id, target_script_id)
            await self.rerun_video_for_script(target_script_id, platform_token=platform_token)
        elif node == "storyboard":
            await self.regenerate_storyboard_and_video(
                target_script_id,
                platform_token=platform_token,
                storyboard_note=note,
            )
        else:
            await self.run_from_storyboard(
                target_script_id,
                platform_token=platform_token,
                storyboard_note=note,
            )

    def _build_account_context(self, account_id: str) -> str:
        if not account_id:
            return ""
        acc = self.repo.get_account(account_id)
        if not acc:
            return ""
        return (
            f"账号: {acc.get('display_name', '')} ({acc.get('username', '')})\n"
            f"定位: {acc.get('positioning', '')}\n"
            f"人设: {acc.get('persona_style', '')}\n"
            f"主页包装: {acc.get('page_packaging', '')}\n"
            f"Bio: {acc.get('bio', '')}\n"
            f"适合方向: {acc.get('content_directions', '')}\n"
            f"主推产品: {acc.get('main_products', '')}"
        )

    @staticmethod
    def _conversion_context_for_product_name(repo: Repository, product_name: str) -> str:
        prod = repo.get_product_by_name(product_name)
        return build_conversion_context(prod)

    def _build_pricing_context(self, prod_obj: dict[str, Any] | None) -> str:
        return pricing_context_for_product(prod_obj)

    def _build_difficulty_context(self, level: str) -> str:
        levels = self.repo.list_difficulty_levels()
        for item in levels:
            if item.get("name") == level:
                return (
                    f"{level}：{item.get('core_form', '')}，"
                    f"分镜2-3镜（禁止插电/插口镜头），"
                    f"结构{item.get('structure', '')}，"
                    f"关键词{item.get('keywords', '')}"
                )
        return level

    async def generate_scripts_for_batch(
        self,
        batch_id: str,
        product: str,
        direction: str,
        count: int,
        extra_instruction: str = "",
        selling_points: str = "",
        product_specs: str = "",
        direction_description: str = "",
        product_obj: dict[str, Any] | None = None,
        difficulty_level: str = "低级",
        account_id: str = "",
        language: str = "英语",
        producer: str = "",
        use_first_frame: bool = False,
    ) -> list[str]:
        script_ids = [f"S{batch_id}-{i:02d}" for i in range(1, count + 1)]
        account_context = self._build_account_context(account_id)
        brand = brand_from_product(product_obj)
        brand_context = brand.script_instruction(language)
        conversion_context = build_conversion_context(product_obj)
        pricing_context = pricing_context_for_product(
            product_obj, conversion_method=resolve_conversion_method(product_obj)
        )
        difficulty_context = self._build_difficulty_context(difficulty_level)
        batch_bp = self._blueprint_for_batch_id(batch_id)
        if batch_bp:
            batch_bp = merge_batch_overrides(
                batch_bp,
                direction=direction,
                count=count,
                extra_instruction=extra_instruction,
            )
        blueprint_block = build_production_context(batch_bp) if batch_bp else ""
        if not batch_bp:
            blueprint_block = self._default_production_brief()
        merged_extra = extra_instruction
        if blueprint_block:
            merged_extra = (
                f"{blueprint_block}\n\n{extra_instruction}".strip()
                if extra_instruction.strip()
                else blueprint_block
            )
        specs_for_prompt = product_specs
        if specs_for_prompt.strip():
            plug_note = (
                "【成片约束】以下接口说明仅供口播参考；画面禁止插插座/插口特写/手插插头。\n\n"
                if not batch_bp
                else "【产品规格】\n\n"
            )
            specs_for_prompt = plug_note + specs_for_prompt.strip()
        llm_sem = asyncio.Semaphore(max(1, self.settings.llm_max_concurrency))
        stagger = self.settings.llm_request_interval_sec

        for i, script_id in enumerate(script_ids, 1):
            self.repo.create_script(
                {
                    "id": script_id,
                    "batch_id": batch_id,
                    "product": product,
                    "direction": direction,
                    "theme": f"等待生成 ({i}/{count})",
                    "hook": "",
                    "outline": "",
                    "cta": "",
                    "shots": [],
                    "review_status": "排队中",
                    "flow_status": "排队中",
                    "difficulty_level": difficulty_level,
                    "account_id": account_id,
                    "language": language,
                    "producer": producer,
                    "use_first_frame": int(bool(use_first_frame)),
                }
            )

        inject_variants = should_inject_variant_direction(batch_bp)
        lib_path = effective_direction_library(batch_bp) if batch_bp else ""
        variant_scripts = (
            list(batch_bp.creative.variant_scripts) if batch_bp and batch_bp.creative.variant_scripts else []
        )
        pv_truth = (
            dict(batch_bp.creative.product_visual_truth)
            if batch_bp and batch_bp.creative.product_visual_truth
            else {}
        )
        script_profile = batch_bp.creative.prompt_profile if batch_bp else ""
        bp_duration = batch_bp.video_spec.duration_sec if batch_bp else 30
        bp_strategy = batch_bp.video_spec.segment_strategy if batch_bp else "dual"

        async def _generate_one(i: int, script_id: str) -> None:
            if stagger > 0 and i > 1:
                await asyncio.sleep(stagger * ((i - 1) % self.settings.llm_max_concurrency))
            async with llm_sem:
                self.repo.update_script(
                    script_id,
                    {
                        "review_status": "生成中",
                        "flow_status": "脚本生成中",
                        "theme": f"脚本生成中 ({i}/{count})",
                    },
                )
                dir_extra = ""
                if inject_variants:
                    dir_extra = format_direction_block(
                        i,
                        library_path=lib_path,
                        variant_scripts=variant_scripts or None,
                        product_visual_truth=pv_truth,
                    )
                script_extra = (
                    f"{merged_extra}\n\n{dir_extra}".strip() if dir_extra else merged_extra
                )
                script_data = normalize_script_data(
                    await self.llm.generate_script(
                        product=product,
                        direction=direction,
                        selling_points=selling_points,
                        product_specs=specs_for_prompt,
                        direction_description=direction_description,
                        pricing_context=pricing_context,
                        account_context=account_context,
                        conversion_context=conversion_context,
                        difficulty_context=difficulty_context,
                        extra_instruction=script_extra,
                        variant_index=i,
                        language=language,
                        brand_context=brand_context,
                        prompt_profile=script_profile,
                        duration_sec=bp_duration,
                        segment_strategy=bp_strategy,
                    )
                )
                if (
                    batch_bp
                    and batch_bp.video_spec.segment_strategy == "single"
                    and batch_bp.video_spec.duration_sec <= 15
                ):
                    shots = script_data.get("shots") or []
                    max_t = _max_shot_end_sec(shots)
                    words = count_script_audio_words(shots, language=language)
                    if max_t > 15 or words > 55:
                        script_data = normalize_script_data(
                            await self.llm.regenerate_script(
                                product=product,
                                direction=direction,
                                review_note=(
                                    f"违反 15s 单段预算：分镜最大时间 {max_t:.0f}s，口播 {words} 词。"
                                    "必须 ONE shot 0–15s，38–52 词，禁止 30s 双段/Part A/B。"
                                ),
                                original_summary=Repository.script_summary(
                                    {**script_data, "id": script_id}
                                ),
                                account_context=account_context,
                                conversion_context=conversion_context,
                                selling_points=selling_points,
                                product_specs=specs_for_prompt,
                                pricing_context=pricing_context,
                                difficulty_context=difficulty_context,
                                language=language,
                                brand_context=brand_context,
                                prompt_profile=script_profile,
                                duration_sec=bp_duration,
                                segment_strategy=bp_strategy,
                            )
                        )
                self.repo.update_script(
                    script_id,
                    {
                        "theme": script_data.get("theme", ""),
                        "hook": script_data.get("hook", ""),
                        "outline": script_data.get("outline", ""),
                        "cta": script_data.get("cta", ""),
                        "shots": script_data.get("shots", []),
                        "review_status": "待审核",
                        "flow_status": "已生成",
                    },
                )

        try:
            await asyncio.gather(*(_generate_one(i, sid) for i, sid in enumerate(script_ids, 1)))
        except Exception as exc:
            err = str(exc)[:500]
            for script_id in script_ids:
                script = self.repo.get_script(script_id)
                if script and script.get("review_status") in ("生成中", "排队中"):
                    self.repo.update_script(
                        script_id,
                        {
                            "review_status": "失败",
                            "flow_status": "生成失败",
                            "review_note": err,
                        },
                    )
            raise
        return script_ids

    def begin_script_review(
        self,
        script_id: str,
        *,
        status: str,
        note: str = "",
        reviewer: str = "",
    ) -> None:
        """同步更新审核状态，列表可立即刷新。"""
        script = self.repo.get_script(script_id)
        if not script:
            raise ValueError(f"脚本不存在: {script_id}")

        if script["flow_status"] in ("进入Prompt", "进入人工剪辑", "已终止") and script["review_status"] == status:
            return

        updates: dict[str, Any] = {
            "review_status": status,
            "review_note": note,
            "reviewer": reviewer,
        }
        if status == "通过":
            updates["flow_status"] = "Prompt生成中"
        elif status == "不通过-废弃":
            updates["flow_status"] = "已终止"
        elif status == "不通过-人工剪辑":
            updates["flow_status"] = "处理中"
        elif status == "不通过-重生成":
            updates["review_status"] = "重生成中"
            updates["flow_status"] = "重生成中"
        self.repo.update_script(script_id, updates)

    async def complete_script_review(
        self,
        script_id: str,
        *,
        status: str,
        note: str = "",
        reviewer: str = "",
    ) -> None:
        script = self.repo.get_script(script_id)
        if not script:
            return
        try:
            await self._complete_script_review_work(script_id, status=status, note=note, reviewer=reviewer)
        except Exception as exc:  # noqa: BLE001
            self.repo.update_script(
                script_id,
                {"flow_status": "处理失败", "review_note": str(exc)[:500]},
            )
            raise

    async def _complete_script_review_work(
        self,
        script_id: str,
        *,
        status: str,
        note: str = "",
        reviewer: str = "",
    ) -> None:
        script = self.repo.get_script(script_id)
        if not script:
            return

        if status == "通过":
            existing = self.repo.get_prompt_by_script(script_id)
            if not existing:
                await self._create_prompt_from_script(script)
            self.repo.update_script(script_id, {"flow_status": "进入Prompt"})
        elif status == "不通过-人工剪辑":
            await self._create_manual_video(script_id, mode="人工二次剪辑")
            self.repo.update_script(script_id, {"flow_status": "进入人工剪辑"})
        elif status == "不通过-废弃":
            self.repo.update_script(script_id, {"flow_status": "已终止"})
        elif status == "不通过-重生成":
            prod = self.repo.get_product_by_name(script.get("product", ""))
            regen = normalize_script_data(
                await self.llm.regenerate_script(
                    product=script["product"],
                    direction=script["direction"],
                    review_note=note,
                    original_summary=Repository.script_summary(script),
                    account_context=self._build_account_context(script.get("account_id", "")),
                    conversion_context=self._conversion_context_for_product_name(
                        self.repo, script.get("product", "")
                    ),
                    selling_points=(prod or {}).get("selling_points", ""),
                    product_specs=(prod or {}).get("product_specs", ""),
                    pricing_context=pricing_context_for_product(prod) if prod else "",
                    difficulty_context=script.get("difficulty_level", "低级"),
                    language=script.get("language", "英语"),
                    brand_context=brand_from_product(prod).script_instruction(
                        script.get("language", "英语")
                    ),
                )
            )
            self.repo.update_script(
                script_id,
                {
                    "theme": regen.get("theme", ""),
                    "hook": regen.get("hook", ""),
                    "outline": regen.get("outline", ""),
                    "cta": regen.get("cta", ""),
                    "shots": regen.get("shots", []),
                    "review_status": "待审核",
                    "review_note": "",
                    "flow_status": "已生成",
                },
            )

    async def review_script(
        self,
        script_id: str,
        *,
        status: str,
        note: str = "",
        reviewer: str = "",
    ) -> None:
        self.begin_script_review(script_id, status=status, note=note, reviewer=reviewer)
        await self.complete_script_review(script_id, status=status, note=note, reviewer=reviewer)

    def begin_prompt_review(
        self,
        prompt_id: str,
        *,
        status: str,
        note: str = "",
    ) -> None:
        prompt = self.repo.get_prompt(prompt_id)
        if not prompt:
            raise ValueError(f"Prompt 不存在: {prompt_id}")

        if prompt["flow_status"] in ("进入出片", "进入人工剪辑", "已终止") and prompt["review_status"] == status:
            return

        updates: dict[str, Any] = {"review_status": status, "review_note": note}
        if status == "通过":
            updates["flow_status"] = "出片中"
            updates["output_mode"] = "AI直出"
            self._ensure_ai_video_generating({**prompt, "output_mode": "AI直出"})
        elif status == "不通过-废弃":
            updates["flow_status"] = "已终止"
        elif status == "不通过-调Prompt":
            updates["review_status"] = "Prompt重生成中"
            updates["flow_status"] = "Prompt重生成中"
        elif status == "不通过-改人工剪":
            updates["flow_status"] = "处理中"
        self.repo.update_prompt(prompt_id, updates)

    async def complete_prompt_review(
        self,
        prompt_id: str,
        *,
        status: str,
        note: str = "",
        platform_token: str = "",
    ) -> None:
        prompt = self.repo.get_prompt(prompt_id)
        if not prompt:
            return
        script = self.repo.get_script(prompt["script_id"])

        if status == "通过":
            self.repo.update_prompt(prompt_id, {"output_mode": "AI直出"})
            await self._enqueue_ai_video(
                {**prompt, "output_mode": "AI直出"},
                platform_token=platform_token,
            )
            self.repo.update_prompt(prompt_id, {"flow_status": "进入出片"})
        elif status == "不通过-调Prompt":
            if script:
                payload = self._build_storyboard_payload(script)
                previous = (
                    f"Part A (0-15s):\n{prompt.get('prompt_text', '')}\n\n"
                    f"Part B (15-30s):\n{prompt.get('prompt_part_b', '')}"
                )
                result = await self.llm.regenerate_storyboard_prompt(payload, note, previous)
                result = ensure_storyboard_voiceover(result, script)
                kit = payload.get("kit_module_policy")
                result = self._enforce_kit_on_storyboard(result, kit)
                self.repo.update_prompt(
                    prompt_id,
                    {
                        **self._extract_storyboard_fields(
                            result,
                            product_name=script.get("product", ""),
                            language=script.get("language", "英语"),
                            script=script,
                            kit=kit,
                            blueprint=self._blueprint_for_script(script),
                        ),
                        "review_status": "待审核",
                        "review_note": "",
                    },
                )
        elif status == "不通过-废弃":
            self.repo.update_prompt(prompt_id, {"flow_status": "已终止"})
        elif status == "不通过-改人工剪":
            if script:
                await self._create_manual_video(
                    prompt["script_id"], mode="人工二次剪辑", prompt_id=prompt_id
                )
            self.repo.update_prompt(prompt_id, {"flow_status": "进入人工剪辑"})

    async def review_prompt(
        self,
        prompt_id: str,
        *,
        status: str,
        note: str = "",
    ) -> None:
        self.begin_prompt_review(prompt_id, status=status, note=note)
        await self.complete_prompt_review(prompt_id, status=status, note=note)

    @staticmethod
    def _enforce_kit_on_storyboard(
        result: dict[str, Any],
        kit: dict[str, Any] | None,
    ) -> dict[str, Any]:
        if not kit:
            return result
        out = dict(result)
        pu = merge_kit_into_product_understanding(out.get("product_understanding"), kit)
        out["product_understanding"] = pu
        out["negative_prompt"] = append_kit_negative(out.get("negative_prompt", ""), kit)
        return out

    @staticmethod
    def _extract_storyboard_fields(
        result: dict[str, Any],
        *,
        product_name: str = "",
        language: str = "英语",
        script: dict[str, Any] | None = None,
        kit: dict[str, Any] | None = None,
        brand: BrandProfile | None = None,
        blueprint: WorkflowBlueprint | None = None,
    ) -> dict[str, Any]:
        result = ensure_storyboard_voiceover(result, script)
        result = WorkflowOrchestrator._enforce_kit_on_storyboard(result, kit)
        product_understanding = dict(result.get("product_understanding", {}) or {})
        if brand is not None and brand.has_brand:
            # 把品牌写进 spec，供出片/TTS/字幕阶段从 product_spec_json 恢复
            product_understanding["brand"] = brand.display
            if brand.has_pronunciation:
                product_understanding["brand_pronunciation"] = brand.pronunciation.strip()
        spec = annotate_voiceover_spec(
            {
                "product_understanding": product_understanding,
                "interaction_beats": result.get("interaction_beats", []),
                "narrative_arc": result.get("narrative_arc", {}),
                "voiceover_part_a": result.get("voiceover_part_a", []),
                "voiceover_part_b": result.get("voiceover_part_b", []),
                "voice_profile": result.get("voice_profile", {}),
                "language": language,
            },
            language=language,
        )
        voice_hint = voice_hint_for_seedance(
            spec.get("voice_profile") or {}, brand=brand, language=language
        )
        script = script or {}
        native_ugc = use_ugc_viral_prompt_format(
            get_settings(),
            blueprint=blueprint,
        )
        if native_ugc:
            spec["ugc_viral_15s_native"] = True
        visual_only = seedance_visual_only(
            get_settings(),
            blueprint=blueprint,
        )
        part_a_llm = result.get("prompt_part_a") or result.get("prompt", "")
        part_b_llm = result.get("prompt_part_b", "")
        return {
            "prompt_text": resolve_segment_prompt(
                part="a",
                llm_text=part_a_llm,
                spec=spec,
                product_name=product_name,
                voice_profile_hint=voice_hint,
                visual_only=visual_only,
                native_ugc_15s=native_ugc,
            ),
            "prompt_part_b": resolve_segment_prompt(
                part="b",
                llm_text=part_b_llm,
                spec=spec,
                product_name=product_name,
                voice_profile_hint=voice_hint,
                visual_only=visual_only,
                native_ugc_15s=False,
            ),
            "product_spec_json": json.dumps(spec, ensure_ascii=False),
            "negative_prompt": result.get("negative_prompt", ""),
            "duration_sec": result.get("duration_sec", 30),
            "segment_duration_sec": result.get("segment_duration_sec", 15),
            "aspect_ratio": result.get("aspect_ratio", "9:16"),
        }

    def _build_storyboard_payload(self, script: dict[str, Any]) -> dict[str, Any]:
        lang = script.get("language", "英语")
        bp = self._blueprint_for_script(script)
        native = use_native_seedance_15s(self.settings, blueprint=bp)
        viral = use_ugc_viral_prompt_format(self.settings, blueprint=bp)
        mode_summary = production_mode_summary(self.settings, blueprint=bp)
        if native:
            audio_note = (
                f"【产线模式】{mode_summary}。"
                "口播写在 prompt_part_a 的 [0-3s Hook][3-10s Core][10-15s CTA] 内 [Voiceover: ...]；"
                "禁止后期 TTS、禁止烧录字幕；画面禁止可读字幕/平台 Logo"
                if not is_spanish(lang)
                else f"【产线模式】{mode_summary}。无后期 TTS/字幕"
            )
        else:
            audio_note = (
                "Seedance 生成口播+画面；禁止画面可读字幕/花字（仅箭头/贴纸）；"
                "字幕策略见 Blueprint production"
                if not is_spanish(lang)
                else "Seedance 生成西语口播+画面；字幕策略见 Blueprint"
            )
        if bp and bp.creative.narrative_rule.strip():
            narrative_rule = bp.creative.narrative_rule.strip()
        else:
            narrative_rule = "按内容方向、对标风格与补充指令组织叙事节拍（竖屏 TikTok）"
        if bp and bp.creative.reference_style.strip():
            reference_style = bp.creative.reference_style.strip()
        else:
            reference_style = (
                "竖屏真实场景、节奏适合 TikTok；镜头数与 pacing 以补充指令为准"
            )
        cp = (bp.creative.creator_persona if bp else {}) or {}
        payload: dict[str, Any] = {
            "theme": script.get("theme", ""),
            "hook": script.get("hook", ""),
            "outline": script.get("outline", ""),
            "cta": script.get("cta", ""),
            "suspense_hook": script.get("suspense_hook", ""),
            "narrative_rule": narrative_rule,
            "audio_only": audio_note,
            "reference_style": reference_style,
            "shots": normalize_shots(script.get("shots", [])),
            "product": script.get("product", ""),
            "direction": script.get("direction", ""),
            "language": script.get("language", "英语"),
            "difficulty_level": script.get("difficulty_level", ""),
        }
        if cp:
            payload["creator_persona"] = cp
        if bp and bp.creative.product_visual_truth:
            payload["product_visual_truth"] = bp.creative.product_visual_truth
        if bp and bp.creative.cta_pattern:
            payload["cta_pattern"] = bp.creative.cta_pattern
        account_id = script.get("account_id", "")
        prod = self.repo.get_product_by_name(script.get("product", ""))
        brand = brand_from_product(prod)
        payload["brand"] = brand.display
        payload["brand_pronunciation"] = brand.spoken if brand.has_pronunciation else ""
        if account_id:
            acc = self.repo.get_account(account_id)
            if acc:
                payload["account_persona"] = {
                    "display_name": acc.get("display_name", ""),
                    "username": acc.get("username", ""),
                    "positioning": acc.get("positioning", ""),
                    "persona_style": acc.get("persona_style", ""),
                    "page_packaging": acc.get("page_packaging", ""),
                    "bio": acc.get("bio", ""),
                    "content_directions": acc.get("content_directions", ""),
                    "main_products": acc.get("main_products", ""),
                }
                payload["voice_profile"] = build_voice_profile(acc, language=lang)
        if prod:
            payload["conversion_context"] = build_conversion_context(prod)
            payload["product_conversion_method"] = resolve_conversion_method(prod)
            payload["product_selling_points"] = prod.get("selling_points", "")
            if prod.get("product_specs"):
                spec_prefix = (
                    "【产品规格】\n\n" if bp else
                    "【成片约束】以下接口说明仅供口播参考；画面禁止插插座/插口特写/手插插头。\n\n"
                )
                payload["product_specs"] = spec_prefix + prod.get("product_specs", "")
            payload["reference_image_count"] = len(parse_product_image_urls(prod))
            kit = build_kit_constraint(
                prod.get("name", ""), prod.get("product_specs", ""), brand=brand
            )
            if kit:
                payload["kit_module_policy"] = kit
            pricing = pricing_context_for_product(
                prod, conversion_method=resolve_conversion_method(prod)
            )
            if pricing:
                payload["product_pricing"] = pricing
        elif script.get("product"):
            payload["conversion_context"] = self._conversion_context_for_product_name(
                self.repo, script.get("product", "")
            )
        payload["reference_image_policy"] = {
            "purpose": "仅锁定产品外观（造型、配色、接口布局），不得复刻参考图中的人物/背景/未脚本化的第二台设备",
            "forbidden_from_reference": [
                "people and faces",
                "thumbs-up gestures",
                "background props from photo",
                "extra products not listed in script shots",
                f"extra {brand.display} modules beyond kit_module_policy whitelist"
                if brand.has_brand
                else "extra branded modules beyond kit_module_policy whitelist",
                f"brand logos on mugs, cups, tents, clothing, or any prop ({brand.display} logo only on product unit)"
                if brand.has_brand
                else "brand logos on mugs, cups, tents, clothing, or any prop (logo only on product unit)",
            ],
            "frame_default": "product-only or hands-only for scripted interactions",
        }
        payload["visual_graphics_policy"] = (
            "生成画面禁止可读字幕/花字/标题字；仅允许图形贴纸（红箭头、无字折扣徽章、星星等）。"
            "CTA 结尾用拇指向下/箭头贴纸+口播催促，不要在画面写字。"
            if native
            else "生成画面禁止可读字幕/花字/标题字；仅允许图形贴纸（红箭头、无字折扣徽章、星星等）。"
            "口播文案写入 voiceover 表，上屏字幕由后期烧录；CTA 结尾用箭头图标+口播催促，不要在画面写字。"
        )
        if native:
            payload["production_mode_native"] = True
            payload["production_mode_summary"] = mode_summary
        if bp and bp.creative.prompt_profile:
            payload["script_prompt_profile"] = bp.creative.prompt_profile
        if bp and bp.creative.storyboard_profile:
            payload["storyboard_prompt_profile"] = bp.creative.storyboard_profile
        if viral:
            payload["ugc_viral_15s_native"] = True
        beat = (bp.creative.beat_structure if bp else "") or ""
        if beat.strip():
            payload["ugc_15s_beat_structure"] = beat.strip()
        elif viral:
            payload["ugc_15s_beat_structure"] = (
                "Viral UGC 三段式（英文 prompt）："
                "[0-3s Hook] → [Voiceover: ...]；"
                "[3-10s Core] 产品交互按 product_visual_truth → [Voiceover: ...]；"
                "[10-15s CTA] 拇指/箭头指向下 → [Voiceover: ...]。"
                "handheld POV；遵守 creative.forbidden。"
            )
        variant_i = 1
        sid = script.get("id", "")
        m = re.search(r"-(\d+)$", sid)
        if m:
            variant_i = int(m.group(1))
        if bp and should_inject_variant_direction(bp):
            pv = dict(bp.creative.product_visual_truth or {})
            dir_block = format_direction_block(
                variant_i,
                library_path=effective_direction_library(bp),
                variant_scripts=list(bp.creative.variant_scripts) or None,
                product_visual_truth=pv,
            )
            if dir_block:
                payload["creative_direction_block"] = dir_block
        if bp and bp.reference.product_reference_video_url:
            payload["product_reference_video_policy"] = (
                "Seedance reference_video 仅学产品：横撕条包、粉末颜色质地、包装；"
                "禁止复刻参考视频人物/剧情/背景。"
            )
        dir_obj = self.repo.get_direction_by_short_code(script.get("direction", ""))
        if not dir_obj:
            for d in self.repo.list_directions():
                if d.get("name") == script.get("direction"):
                    dir_obj = d
                    break
        if dir_obj:
            payload["direction_description"] = dir_obj.get("description", "")
        shots = payload.get("shots") or []
        script_words = count_script_audio_words(shots, language=lang)
        dur_sec = int(payload.get("duration_sec") or 30)
        seg_strat = str(payload.get("segment_strategy") or "dual")
        payload["voiceover_budget"] = voiceover_budget_hint(
            lang, duration_sec=dur_sec, segment_strategy=seg_strat
        )
        payload["script_audio_word_count"] = script_words
        payload["script_audio_estimated_sec"] = round(estimate_tts_seconds(script_words, language=lang), 1)
        return payload

    async def _create_prompt_from_script(self, script: dict[str, Any]) -> None:
        payload = self._build_storyboard_payload(script)
        kit = payload.get("kit_module_policy")
        brand = brand_from_product(self.repo.get_product_by_name(script.get("product", "")))
        account_id = script.get("account_id", "")
        acc = self.repo.get_account(account_id) if account_id else None
        default_voice = build_voice_profile(acc, language=script.get("language", "英语"))
        result = await self.llm.generate_storyboard_prompt(payload)
        result = ensure_storyboard_voiceover(result, script)
        result = self._enforce_kit_on_storyboard(result, kit)
        if not (result.get("voiceover_part_a") or result.get("voiceover_part_b")):
            regen_note = (
                "上次输出缺少 voiceover_part_a / voiceover_part_b（口播表为空会导致成片无声）。"
                "必须按 JSON 示例完整输出西语/英语口播表，每条含 time + spoken。"
            )
            result = await self.llm.regenerate_storyboard_prompt(
                payload, regen_note, previous_prompt=""
            )
            result = ensure_storyboard_voiceover(result, script)
            result = self._enforce_kit_on_storyboard(result, kit)
        if not result.get("voice_profile"):
            result["voice_profile"] = default_voice
        prompt_id = f"P{script['id']}"
        bp = self._blueprint_for_script(script)
        fields = self._extract_storyboard_fields(
            result,
            product_name=script.get("product", ""),
            language=script.get("language", "英语"),
            script=script,
            kit=kit,
            brand=brand,
            blueprint=bp,
        )
        if bp:
            fields["segment_duration_sec"] = bp.video_spec.segment_duration_sec
            fields["duration_sec"] = bp.video_spec.duration_sec
            fields["aspect_ratio"] = bp.video_spec.aspect_ratio
        else:
            fields["duration_sec"] = int(self.settings.video_default_duration_sec or 15)
            fields["segment_duration_sec"] = fields["duration_sec"]
            if self._is_single_segment_video({"script_id": script["id"], **fields}):
                fields["duration_sec"] = fields["segment_duration_sec"]
        self.repo.create_prompt(
            {
                "id": prompt_id,
                "script_id": script["id"],
                "output_mode": "AI直出",
                **fields,
            }
        )

    def begin_video_retry(self, video_id: str) -> None:
        video = self.repo.get_video(video_id)
        if not video:
            raise ValueError("视频不存在")
        if video.get("output_status") != "失败":
            raise ValueError("只能重试状态为「失败」的视频")
        if not self.repo.get_prompt(video.get("prompt_id", "")):
            raise ValueError("关联 Prompt 不存在")
        self.repo.update_video(
            video_id,
            {
                "output_status": "生成中",
                "fail_reason": "",
                "note": "",
                "video_url": "",
                "segment_urls_json": "",
            },
        )

    async def complete_video_retry(self, video_id: str, platform_token: str = "") -> None:
        video = self.repo.get_video(video_id)
        if not video:
            return
        prompt = self.repo.get_prompt(video.get("prompt_id", ""))
        if not prompt:
            return
        await self._generate_ai_video(prompt, video_id, platform_token=platform_token)

    @staticmethod
    def _is_manual_video(video: dict[str, Any]) -> bool:
        mode = video.get("output_mode") or ""
        vid = video.get("id") or ""
        return "人工" in mode or vid.endswith("-manual")

    def begin_segment_regenerate(self, video_id: str, segment: str) -> None:
        if segment not in ("part_a", "part_b"):
            raise ValueError("segment 须为 part_a 或 part_b")
        video = self.repo.get_video(video_id)
        if not video:
            raise ValueError("视频不存在")
        if self._is_manual_video(video):
            raise ValueError("人工剪辑任务不支持分段重生成")
        if video.get("output_status") == "生成中":
            raise ValueError("视频正在生成中，请稍候完成后再试")
        prompt = self.repo.get_prompt(video.get("prompt_id", ""))
        if not prompt:
            raise ValueError("关联 Prompt 不存在")
        seg = self._read_segment_json(video_id)
        if segment == "part_b" and not seg.get("part_a"):
            raise ValueError("须先有 Part A 才能重生成 Part B")
        label = "Part A (0-15s)" if segment == "part_a" else "Part B (15-30s)"
        seg["progress"] = {
            "phase": segment,
            "percent": 0,
            "seedance_status": "pending",
            "message": f"正在重新生成 {label}…",
            "updated_at": datetime.now(UTC).isoformat(),
        }
        self.repo.update_video(
            video_id,
            {
                "output_status": "生成中",
                "video_url": "",
                "fail_reason": "",
                "note": f"正在重新生成 {label}…",
                "segment_urls_json": json.dumps(seg, ensure_ascii=False),
            },
        )

    async def complete_segment_regenerate(
        self, video_id: str, segment: str, platform_token: str = ""
    ) -> None:
        video = self.repo.get_video(video_id)
        if not video:
            return
        prompt = self.repo.get_prompt(video.get("prompt_id", ""))
        if not prompt:
            return
        token = self._platform_token_for_video(video_id, platform_token)
        if token:
            self._store_platform_token(video_id, token)
        ctx = self._prompt_video_context(prompt)
        seg = self._read_segment_json(video_id)
        engine = self._video_engine_label()
        try:
            if segment == "part_a":
                first_frame_url = await self._ensure_first_frame(video_id, ctx)
                result_a = await self.video.generate(
                    prompt=ctx["part_a"],
                    duration_sec=ctx["segment_duration"],
                    aspect_ratio=ctx["aspect_ratio"],
                    image_urls=ctx["image_urls"],
                    first_frame_url=first_frame_url,
                    voiceover_script=ctx["vo_a"],
                    negative_prompt=ctx["negative"],
                    voice_profile=ctx["voice_profile"],
                    kit_constraint_text=ctx.get("kit_constraint_text", ""),
                    brand=ctx.get("brand"),
                    reference_video_urls=ctx.get("reference_video_urls"),
                    product_reference_frames=bool(ctx.get("product_reference_frames")),
                    progress_callback=self._make_seedance_progress_cb(video_id, "part_a", 0, 50),
                    segment_label="part_a",
                    platform_token=token,
                    billing_biz_no=self._billing_biz_no(video_id, "part_a"),
                )
                if result_a.get("status") == "placeholder":
                    self.repo.update_video(
                        video_id, {"output_status": "排队中", "note": result_a.get("message", "")}
                    )
                    return
                if result_a.get("charge"):
                    self._store_segment_charge(video_id, "part_a", result_a["charge"])
                url_a = result_a.get("video_url", "")
                if not url_a:
                    raise RuntimeError(f"{engine} 未返回 Part A 视频 URL")
                seg["part_a"] = url_a
                url_b = seg.get("part_b", "")
                if url_b:
                    await self._complete_ai_video(
                        prompt,
                        video_id,
                        url_a=url_a,
                        result_b={"video_url": url_b},
                        platform_token=token,
                    )
                else:
                    seg["progress"] = {
                        **seg.get("progress", {}),
                        "phase": "part_b",
                        "percent": 50,
                        "message": "Part A 完成，开始 Part B…",
                        "updated_at": datetime.now(UTC).isoformat(),
                    }
                    self.repo.update_video(
                        video_id,
                        {
                            "segment_urls_json": json.dumps(seg, ensure_ascii=False),
                            "note": "Part A 重生成完成 · 开始 Part B…",
                        },
                    )
                    await self._complete_ai_video(
                        prompt, video_id, url_a=url_a, platform_token=token
                    )
            else:
                url_a = seg.get("part_a", "")
                if not url_a:
                    raise ValueError("须先有 Part A 才能重生成 Part B")
                first_frame_url_part_b = await self._ensure_first_frame(video_id, ctx, part="b")
                result_b = await self.video.generate(
                    prompt=ctx["part_b"],
                    duration_sec=ctx["segment_duration"],
                    aspect_ratio=ctx["aspect_ratio"],
                    image_urls=ctx["image_urls"],
                    first_frame_url=first_frame_url_part_b,
                    voiceover_script=ctx["vo_b"],
                    negative_prompt=ctx["negative"],
                    voice_profile=ctx["voice_profile"],
                    kit_constraint_text=ctx.get("kit_constraint_text", ""),
                    brand=ctx.get("brand"),
                    reference_video_urls=ctx.get("reference_video_urls"),
                    product_reference_frames=bool(ctx.get("product_reference_frames")),
                    progress_callback=self._make_seedance_progress_cb(video_id, "part_b", 50, 40),
                    segment_label="part_b",
                    platform_token=token,
                    billing_biz_no=self._billing_biz_no(video_id, "part_b"),
                )
                if result_b.get("status") == "placeholder":
                    self.repo.update_video(
                        video_id, {"output_status": "排队中", "note": result_b.get("message", "")}
                    )
                    return
                if result_b.get("charge"):
                    self._store_segment_charge(video_id, "part_b", result_b["charge"])
                await self._complete_ai_video(
                    prompt, video_id, url_a=url_a, result_b=result_b, platform_token=token
                )
        except Exception as exc:  # noqa: BLE001
            self.repo.update_video(video_id, {"output_status": "失败", "fail_reason": str(exc)})

    def delete_video_record(self, video_id: str) -> None:
        video = self.repo.get_video(video_id)
        if not video:
            raise ValueError("视频不存在")
        if video.get("output_status") == "生成中":
            raise ValueError("视频正在生成中，请稍候或先续跑完成后再删除")
        self.repo.delete_video(video_id)

    async def burn_subtitles_for_video(self, video_id: str) -> None:
        video = self.repo.get_video(video_id)
        if not video:
            raise ValueError("视频不存在")
        if self._is_manual_video(video):
            raise ValueError("人工剪辑任务请手动加字幕")
        prompt = self.repo.get_prompt(video.get("prompt_id", ""))
        if not prompt:
            raise ValueError("关联 Prompt 不存在")
        ctx = self._prompt_video_context(prompt)
        if not ctx["vo_a"] and not ctx["vo_b"]:
            raise ValueError("无口播台词表，无法烧录字幕")
        video_url = video.get("video_url") or ""
        if not video_url.startswith("/uploads/videos/"):
            raise ValueError("仅支持本地成片烧录字幕")
        try:
            local_path = resolve_burn_input_path(video_id)
        except FileNotFoundError as exc:
            raise FileNotFoundError("无字幕源片不存在，请重新出片后再烧录") from exc
        tts_events = None
        tts_detail = ""
        if get_settings().tts_post_enabled:
            try:
                acc, acc_id = self._tts_account_context(ctx)
                tts_result = await apply_tts_post_production(
                    local_path,
                    ctx["vo_a"],
                    ctx["vo_b"],
                    voice_profile=ctx.get("voice_persona"),
                    account=acc,
                    account_id=acc_id,
                    brand=ctx.get("brand"),
                )
                tts_events = tts_result.events
                tts_detail = tts_result.detail
            except Exception as tts_exc:  # noqa: BLE001
                tts_detail = f"Edge TTS 失败，改用识别对齐: {str(tts_exc)[:160]}"
        sub_result = await burn_subtitles_on_video(
            str(local_path),
            voiceover_a=ctx["vo_a"],
            voiceover_b=ctx["vo_b"],
            video_id=video_id,
            tts_events=tts_events,
            tts_detail=tts_detail,
            brand=ctx.get("brand"),
        )
        if sub_result.get("skipped"):
            raise ValueError("台词表为空")
        mode = sub_result.get("timing_mode", "")
        align_status = sub_result.get("subtitle_align_status") or (
            "TTS对齐"
            if mode == "tts_aligned"
            else "口播对齐"
            if mode == "audio_aligned"
            else "剧本估算"
        )
        align_detail = sub_result.get("subtitle_align_detail", "")
        base_note = (video.get("note") or "").split(" · 已烧录英文字幕")[0]
        self.repo.update_video(
            video_id,
            {
                "video_url": sub_result["video_url"],
                "subtitle_status": "已完成",
                "subtitle_align_status": align_status,
                "subtitle_align_detail": align_detail,
                "note": base_note + " · 已烧录英文字幕",
            },
        )

    async def retry_failed_video(self, video_id: str) -> None:
        self.begin_video_retry(video_id)
        await self.complete_video_retry(video_id)

    def _ensure_ai_video_generating(self, prompt: dict[str, Any]) -> str:
        """Prompt 通过时立即创建/更新视频记录为「生成中」，供前端展示。"""
        video_id = f"V{prompt['id']}"
        existing = self.repo.get_video(video_id)
        if existing and existing.get("output_status") in ("待交付", "已交付"):
            return video_id
        engine = self._video_engine_label()
        fields = {
            "output_status": "生成中",
            "fail_reason": "",
            "note": f"{engine} 已启动（Part A 0-15s）…",
            "output_mode": "AI直出",
        }
        if existing:
            self.repo.update_video(video_id, fields)
        else:
            self.repo.create_video(
                {
                    "id": video_id,
                    "prompt_id": prompt["id"],
                    "script_id": prompt["script_id"],
                    **fields,
                }
            )
        self._write_seedance_progress(
            video_id,
            phase="part_a",
            percent=0,
            seedance_status="pending",
            provider="platform" if self._use_platform_video() else "seedance",
            message=f"{engine} 已启动，正在提交 Part A…",
        )
        return video_id

    async def _enqueue_ai_video(
        self, prompt: dict[str, Any], *, platform_token: str = ""
    ) -> None:
        video_id = self._ensure_ai_video_generating(prompt)
        if platform_token.strip():
            self._store_platform_token(video_id, platform_token)
        await self._generate_ai_video(prompt, video_id, platform_token=platform_token)

    def _read_segment_json(self, video_id: str) -> dict[str, Any]:
        video = self.repo.get_video(video_id)
        if not video:
            return {}
        try:
            raw = json.loads(video.get("segment_urls_json") or "{}")
            return raw if isinstance(raw, dict) else {}
        except json.JSONDecodeError:
            return {}

    def _write_seedance_progress(self, video_id: str, **fields: Any) -> None:
        seg = self._read_segment_json(video_id)
        seg["progress"] = {
            **seg.get("progress", {}),
            **fields,
            "updated_at": datetime.now(UTC).isoformat(),
        }
        note = fields.get("message") or fields.get("note", "")
        updates: dict[str, Any] = {
            "segment_urls_json": json.dumps(seg, ensure_ascii=False),
        }
        if note:
            updates["note"] = note
        self.repo.update_video(video_id, updates)

    def _make_seedance_progress_cb(
        self, video_id: str, segment: str, base_pct: int, span_pct: int
    ):
        labels = {"part_a": "Part A (0-15s)", "part_b": "Part B (15-30s)", "concat": "拼接 30s"}

        async def _cb(info: dict[str, Any]) -> None:
            poll = int(info.get("poll") or 0)
            max_polls = int(info.get("max_polls") or 240)
            api_status = info.get("seedance_status") or "unknown"
            task_id = info.get("task_id") or ""
            provider = info.get("provider") or (
                "platform" if self._use_platform_video() else "seedance"
            )
            engine = "主站 AI Video" if provider == "platform" else "Seedance 2.0"
            inner = int(poll / max_polls * span_pct) if max_polls and poll else 0
            percent = min(base_pct + inner, base_pct + span_pct - 1) if span_pct else base_pct
            if api_status == "succeeded":
                percent = base_pct + span_pct
            status_cn = {
                "submitted": "已提交",
                "queued": "排队中",
                "running": "生成中",
                "succeeded": "已完成",
                "failed": "失败",
                "expired": "已过期",
            }.get(api_status, api_status)
            label = labels.get(segment, segment)
            poll_sec = int(
                getattr(self.settings, "platform_video_poll_interval_sec", 5) or 5
                if provider == "platform"
                else getattr(self.settings, "seedance_poll_interval_sec", 3) or 3
            )
            waited_sec = poll * poll_sec
            msg = (
                f"{engine} · {label} · {status_cn} · 约 {percent}%"
                f" · 已等待 {waited_sec // 60}分{waited_sec % 60}秒"
                f" · 轮询 {poll}/{max_polls}"
            )
            if task_id:
                msg += f" · 任务 {task_id}"
            if api_status == "running" and poll > 0 and provider == "seedance":
                msg += "（Seedance 生成较慢，5% 左右属正常，非卡死）"
            self._write_seedance_progress(
                video_id,
                phase=segment,
                task_id=task_id,
                seedance_status=api_status,
                provider=provider,
                poll=poll,
                max_polls=max_polls,
                percent=percent,
                message=msg,
            )

        return _cb

    @staticmethod
    def _sanitize_prompt_for_seedance(text: str) -> str:
        """出片前剔除烧录字幕指令与插电/插口类画面描述。"""
        if not text:
            return text
        out = text
        for pattern in (
            r"\|\s*Burned-in subtitle[^\"\n]*\"[^\"]*\"",
            r"\|\s*Synced subtitle[^\"\n]*\"[^\"]*\"",
            r"burned-in (?:English )?subtitles?[^\n.]*",
            r"on-screen (?:English )?(?:subtitles?|captions?)[^\n.]*",
            r"synced (?:burned-in )?subtitles?[^\n.]*",
            r"white sans-serif text[^\n.]*",
            r"text (?:overlay|with)[^\n.]*(?:shadow|shadows)[^\n.]*",
            r"(?:line\s*\d+|two[- ]line)[^\n.]*(?:text|copy|caption)[^\n.]*",
            r"readable (?:CTA |marketing )?text[^\n.]*",
            r"promotional text on screen[^\n.]*",
            r"[^.\n]{0,120}plug(?:ging|ged|s)?[^.\n]{0,80}(?:outlet|socket|port|AC|wall)[^.\n]*",
            r"[^.\n]{0,120}(?:insert(?:ing|s)?|connect(?:ing|s)?)[^.\n]{0,60}(?:plug|cable|cord)[^.\n]{0,60}(?:outlet|socket|port|wall)[^.\n]*",
            r"[^.\n]{0,120}(?:AC|USB|RV|NEMA)[^.\n]{0,40}(?:outlet|port|socket)[^.\n]*close[- ]?up[^.\n]*",
            r"[^.\n]{0,120}hand[^.\n]{0,40}(?:plug|insert)[^.\n]*",
        ):
            out = re.sub(pattern, "", out, flags=re.IGNORECASE)
        return re.sub(r"\n{3,}", "\n\n", out).strip()

    def _tts_account_context(self, ctx: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        script = ctx.get("script") or {}
        account_id = str(script.get("account_id") or "")
        account = self.repo.get_account(account_id) if account_id else None
        return account, account_id

    def _voice_persona_from_prompt(self, prompt: dict[str, Any]) -> dict[str, str]:
        script = self.repo.get_script(prompt.get("script_id", ""))
        lang = (script or {}).get("language", "英语")
        acc = self.repo.get_account(script.get("account_id", "")) if script else None
        try:
            spec = json.loads(prompt.get("product_spec_json") or "{}")
            profile = dict(spec.get("voice_profile") or {})
            if profile:
                if not profile.get("language"):
                    profile["language"] = lang
                if not profile.get("tts_voice"):
                    profile["tts_voice"] = resolve_tts_voice(
                        profile, account=acc, language=lang
                    )
                return profile
        except json.JSONDecodeError:
            pass
        return build_voice_profile(acc, language=lang)

    def _voice_hint_from_prompt(self, prompt: dict[str, Any]) -> str:
        profile = self._voice_persona_from_prompt(prompt)
        try:
            spec = json.loads(prompt.get("product_spec_json") or "{}")
        except json.JSONDecodeError:
            spec = {}
        return voice_hint_for_seedance(
            profile, brand=brand_from_spec_json(spec), language=profile.get("language")
        )

    def _is_single_segment_video(self, prompt: dict[str, Any]) -> bool:
        script = self.repo.get_script(prompt.get("script_id", ""))
        bp = self._blueprint_for_script(script or {})
        if bp:
            return bp.video_spec.segment_strategy == "single"
        dur = int(prompt.get("duration_sec") or 0)
        if dur <= 0:
            dur = int(self.settings.video_default_duration_sec or 15)
        if dur <= 15:
            return True
        return (self.settings.video_segment_strategy or "single").strip().lower() == "single"

    def _default_production_brief(self) -> str:
        """无 Blueprint 时的默认 TikTok UGC 制片 brief。"""
        dur = int(self.settings.video_default_duration_sec or 15)
        single = (self.settings.video_segment_strategy or "single").strip().lower() == "single"
        seg = f"{dur}s 单段直出" if single else f"约 {dur}s 双段拼接"
        ugc = "TikTok 爆款 UGC：前2秒强钩子、快节奏切镜、真人口播网感、creator talking-to-camera，禁止慢镜头产品片与僵硬 AI 人物。" if self.settings.seedance_ugc_style else ""
        if single and dur <= 15 and not self.settings.tts_post_enabled:
            sub = "无后期 TTS、不烧录字幕；口播内嵌于 Seedance viral prompt [Voiceover]"
        else:
            sub = "【字幕】后期烧录英文字幕。" if self.settings.tts_post_enabled else "【字幕】按 Blueprint 配置"
        return (
            f"【默认成片】竖屏 9:16，{seg}，Seedance 原生配音（必须有声）。\n"
            f"{ugc}\n"
            f"{sub}"
        ).strip()

    async def _postprocess_subtitles(
        self,
        *,
        video_id: str,
        local_path: str,
        ctx: dict[str, Any],
        duration_label: str,
    ) -> tuple[str, str, str, str, str]:
        """返回 (final_url, subtitle_status, align_status, align_detail, subtitle_note)。"""
        final_url = f"/uploads/videos/{Path(local_path).name}"
        subtitle_status = "未开始"
        subtitle_align_status = ""
        subtitle_align_detail = ""
        subtitle_note = ""
        if not (ctx["vo_a"] or ctx["vo_b"]):
            return final_url, subtitle_status, subtitle_align_status, subtitle_align_detail, subtitle_note

        script = ctx.get("script") or {}
        bp = self._blueprint_for_script(script)
        if use_native_seedance_15s(self.settings, blueprint=bp):
            if not should_burn_subtitles(self.settings, blueprint=bp):
                label = subtitle_mode_label(
                    bp.production.subtitles if bp else None,
                    native_audio=True,
                )
                return (
                    final_url,
                    "跳过",
                    subtitle_align_status,
                    subtitle_align_detail,
                    f" · 15s Seedance 原生有声（{label}）",
                )
            # native + burn_in：走下方 Whisper 对齐烧录（tts_on=False）

        if bp and normalize_subtitles(bp.production.subtitles) == "skip":
            return final_url, "跳过", subtitle_align_status, subtitle_align_detail, " · 字幕跳过（后期自行配）"

        tts_on = bool(bp.production.tts) if bp else self.settings.tts_post_enabled
        self._write_seedance_progress(
            video_id,
            phase="subtitles",
            percent=96,
            seedance_status="running",
            message=(
                "正在生成 TTS 口播并烧录字幕…"
                if tts_on
                else "正在识别 Seedance 口播并对齐字幕…"
            ),
        )
        try:
            tts_events = None
            tts_detail = ""
            if tts_on:
                try:
                    acc, acc_id = self._tts_account_context(ctx)
                    tts_result = await apply_tts_post_production(
                        local_path,
                        ctx["vo_a"],
                        ctx["vo_b"],
                        voice_profile=ctx.get("voice_persona"),
                        account=acc,
                        account_id=acc_id,
                        brand=ctx.get("brand"),
                    )
                    tts_events = tts_result.events
                    tts_detail = tts_result.detail
                except Exception as tts_exc:  # noqa: BLE001
                    tts_detail = f"Edge TTS 失败，改用识别对齐: {str(tts_exc)[:160]}"
            sub_result = await burn_subtitles_on_video(
                local_path,
                voiceover_a=ctx["vo_a"],
                voiceover_b=ctx["vo_b"],
                video_id=video_id,
                tts_events=tts_events,
                tts_detail=tts_detail,
                brand=ctx.get("brand"),
            )
            if not sub_result.get("skipped"):
                final_url = sub_result["video_url"]
                subtitle_status = "已完成"
                subtitle_align_status = sub_result.get("subtitle_align_status", "")
                subtitle_align_detail = sub_result.get("subtitle_align_detail", "")
                subtitle_note = " · 已烧录英文字幕"
        except Exception as exc:  # noqa: BLE001
            subtitle_note = f" · 字幕烧录失败: {exc}"
            subtitle_align_status = "口播对齐失败"
            subtitle_align_detail = str(exc)[:240]
        return final_url, subtitle_status, subtitle_align_status, subtitle_align_detail, subtitle_note

    async def _finalize_single_segment_video(
        self,
        prompt: dict[str, Any],
        video_id: str,
        *,
        url_a: str,
        segment_duration: int,
    ) -> None:
        ctx = self._prompt_video_context(prompt)
        engine = self._video_engine_label()
        self._write_seedance_progress(
            video_id,
            phase="finalize",
            percent=90,
            seedance_status="running",
            message=f"{engine} 单段 {segment_duration}s 下载成片…",
        )
        dl = await download_remote_video(url_a, video_id=video_id, segment="part_a")
        label = f"{segment_duration}s 单段"
        final_url, subtitle_status, subtitle_align_status, subtitle_align_detail, subtitle_note = (
            await self._postprocess_subtitles(
                video_id=video_id,
                local_path=dl["local_path"],
                ctx=ctx,
                duration_label=label,
            )
        )
        existing_seg = self._read_segment_json(video_id)
        provider = (existing_seg.get("progress") or {}).get("provider") or (
            "platform" if self._use_platform_video() else "seedance"
        )
        seg_payload: dict[str, Any] = {
            "part_a": url_a,
            "part_b": "",
            "part_a_local": dl.get("part_a_local", ""),
            "part_b_local": "",
            "progress": {
                "phase": "done",
                "percent": 100,
                "seedance_status": "succeeded",
                "provider": provider,
                "message": f"{engine} 单段完成",
                "updated_at": datetime.now(UTC).isoformat(),
            },
        }
        self.repo.update_video(
            video_id,
            {
                "video_url": final_url,
                "output_status": "待交付",
                "subtitle_status": subtitle_status,
                "subtitle_align_status": subtitle_align_status,
                "subtitle_align_detail": subtitle_align_detail,
                "note": f"{label}{subtitle_note}",
                "segment_urls_json": json.dumps(seg_payload, ensure_ascii=False),
            },
        )

    def _prompt_video_context(self, prompt: dict[str, Any]) -> dict[str, Any]:
        script = self.repo.get_script(prompt["script_id"])
        image_urls: list[str] = []
        product_name = (script or {}).get("product", "")
        product_specs = ""
        prod = None
        if script:
            prod = self.repo.get_product_by_name(script["product"])
            if prod:
                image_urls = parse_product_image_urls(prod)
                product_specs = (prod.get("product_specs") or "").strip()
        vo_a: list[dict[str, Any]] = []
        vo_b: list[dict[str, Any]] = []
        try:
            spec = json.loads(prompt.get("product_spec_json") or "{}")
            vo_a, vo_b = resolve_voiceover_tracks(spec, script)
        except json.JSONDecodeError:
            spec = {}
            if script:
                vo_a, vo_b = resolve_voiceover_tracks({}, script)
        # 品牌：优先用当前产品记录，回退到出片时写入 spec 的品牌
        brand = brand_from_product(prod) if prod else brand_from_spec_json(spec)
        voice_hint = self._voice_hint_from_prompt(prompt)
        if script:
            bp = self._blueprint_for_script(script)
            if bp and bp.creative.creator_persona:
                cp = bp.creative.creator_persona
                bits = [
                    f"CREATOR: {cp.get('archetype', '')}",
                    f"Wardrobe: {cp.get('wardrobe', '')}",
                    f"Hair/makeup: {cp.get('hair_makeup', '')}",
                    f"Accessories: {cp.get('accessories', '')}",
                    f"Energy: {cp.get('energy', '')}",
                    f"Memory hook: {cp.get('memory_hook', '')}",
                ]
                voice_hint = "\n".join(b for b in bits if b.split(": ", 1)[-1]) + (
                    f"\n{voice_hint}" if voice_hint else ""
                )
        bp_vid = self._blueprint_for_script(script) if script else None
        visual_only = seedance_visual_only(
            self.settings,
            blueprint=bp_vid,
            prompt=prompt,
        )
        native_ugc = use_ugc_viral_prompt_format(
            self.settings,
            blueprint=bp_vid,
            prompt=prompt,
        )
        part_a = resolve_segment_prompt(
            part="a",
            llm_text=prompt.get("prompt_text", ""),
            spec=spec,
            product_name=product_name,
            voice_profile_hint=voice_hint,
            visual_only=visual_only,
            native_ugc_15s=native_ugc,
        )
        part_b = resolve_segment_prompt(
            part="b",
            llm_text=prompt.get("prompt_part_b", ""),
            spec=spec,
            product_name=product_name,
            voice_profile_hint=voice_hint,
            visual_only=visual_only,
        )
        kit = build_kit_constraint(product_name, product_specs, brand=brand)
        pu = merge_kit_into_product_understanding(spec.get("product_understanding"), kit)
        negative = append_kit_negative(prompt.get("negative_prompt", ""), kit)
        ref_video_urls: list[str] = []
        extra_frames: list[str] = []
        if script:
            bp = self._blueprint_for_script(script)
            if bp:
                if bp.reference.product_reference_video_url:
                    ref_video_urls = [bp.reference.product_reference_video_url]
                extra_frames = list(bp.reference.product_reference_frame_urls or [])
        merged_images = list(dict.fromkeys(image_urls + extra_frames))
        return {
            "script": script,
            "image_urls": merged_images,
            "reference_video_urls": ref_video_urls,
            "product_reference_frames": bool(extra_frames),
            "product_name": product_name,
            "product_specs": product_specs,
            "brand": brand,
            "interaction_beats": spec.get("interaction_beats") or [],
            "product_understanding": pu,
            "kit_constraint": kit,
            "kit_constraint_text": (kit or {}).get("constraint_text", ""),
            "segment_duration": int(prompt.get("segment_duration_sec") or 15),
            "part_a": self._sanitize_prompt_for_seedance(part_a),
            "part_b": self._sanitize_prompt_for_seedance(part_b),
            "aspect_ratio": prompt.get("aspect_ratio") or "9:16",
            "negative": negative,
            "vo_a": vo_a,
            "vo_b": vo_b,
            "voice_profile": self._voice_hint_from_prompt(prompt),
            "voice_persona": self._voice_persona_from_prompt(prompt),
            "use_first_frame": bool(int((script or {}).get("use_first_frame", 0) or 0)),
        }

    async def _ensure_first_frame(self, video_id: str, ctx: dict[str, Any], *, part: str = "a") -> str:
        """复杂交互产品：Part A/B 出片前用 Nano Banana 生成首帧图（已存在则复用）。"""
        if not ctx.get("use_first_frame"):
            return ""
        part_key = (part or "a").lower().strip()
        if part_key not in ("a", "b"):
            part_key = "a"
        col = "first_frame_url" if part_key == "a" else "first_frame_url_part_b"
        visual_key = "part_a" if part_key == "a" else "part_b"
        phase = "first_frame" if part_key == "a" else "first_frame_part_b"
        progress_msg = (
            "正在用 Nano Banana 生成首帧交互图…"
            if part_key == "a"
            else "正在生成 Part B 首帧图…"
        )
        video = self.repo.get_video(video_id)
        existing = (video or {}).get(col) or ""
        if existing:
            return existing
        from src.pipeline.first_frame import generate_first_frame_image

        self._write_seedance_progress(
            video_id,
            phase=phase,
            percent=0,
            seedance_status="running",
            message=progress_msg,
        )
        file_stem = f"{video_id}_b" if part_key == "b" else video_id
        try:
            url = await generate_first_frame_image(
                visual_prompt=ctx.get(visual_key, ""),
                product_image_urls=ctx.get("image_urls", []),
                file_stem=file_stem,
                product_name=ctx.get("product_name", ""),
                product_specs=ctx.get("product_specs", ""),
                interaction_beats=ctx.get("interaction_beats") or [],
                product_understanding=ctx.get("product_understanding") or {},
                kit_constraint=ctx.get("kit_constraint"),
                brand=ctx.get("brand"),
            )
        except Exception as exc:  # noqa: BLE001
            # 首帧图失败不阻断出片，退回纯参考图模式
            fail_label = "Part B 首帧图" if part_key == "b" else "首帧图"
            self._write_seedance_progress(
                video_id,
                phase=phase,
                percent=0,
                seedance_status="running",
                message=f"{fail_label}生成失败，改用参考图直接出片：{str(exc)[:160]}",
            )
            return ""
        self.repo.update_video(video_id, {col: url})
        return url

    async def _finalize_concat_video(
        self,
        prompt: dict[str, Any],
        video_id: str,
        *,
        url_a: str,
        url_b: str,
        segment_duration: int,
    ) -> None:
        ctx = self._prompt_video_context(prompt)
        engine = self._video_engine_label()
        self._write_seedance_progress(
            video_id,
            phase="concat",
            percent=92,
            seedance_status="running",
            message=f"{engine} 两段已完成，正在拼接 30s 成片…",
        )
        concat_result = await concat_remote_videos(url_a, url_b, video_id=video_id)
        label = f"30s（2×{segment_duration}s 拼接）"
        final_url, subtitle_status, subtitle_align_status, subtitle_align_detail, subtitle_note = (
            await self._postprocess_subtitles(
                video_id=video_id,
                local_path=concat_result["local_path"],
                ctx=ctx,
                duration_label=label,
            )
        )
        if final_url == f"/uploads/videos/{Path(concat_result['local_path']).name}" and not subtitle_note:
            final_url = concat_result["video_url"]

        existing_seg = self._read_segment_json(video_id)
        provider = (existing_seg.get("progress") or {}).get("provider") or (
            "platform" if self._use_platform_video() else "seedance"
        )
        seg_payload: dict[str, Any] = {
            "part_a": url_a,
            "part_b": url_b,
            "part_a_local": concat_result.get("part_a_local", ""),
            "part_b_local": concat_result.get("part_b_local", ""),
            "progress": {
                "phase": "done",
                "percent": 100,
                "seedance_status": "succeeded",
                "provider": provider,
                "message": f"{engine} 全流程完成",
                "updated_at": datetime.now(UTC).isoformat(),
            },
        }
        if existing_seg.get("platform_token"):
            seg_payload["platform_token"] = existing_seg["platform_token"]
        if existing_seg.get("charges"):
            seg_payload["charges"] = existing_seg["charges"]
        self.repo.update_video(
            video_id,
            {
                "video_url": final_url,
                "output_status": "待交付",
                "subtitle_status": subtitle_status,
                "subtitle_align_status": subtitle_align_status,
                "subtitle_align_detail": subtitle_align_detail,
                "note": f"30s（2×{segment_duration}s 拼接）{subtitle_note}",
                "segment_urls_json": json.dumps(seg_payload, ensure_ascii=False),
            },
        )

    async def _complete_ai_video(
        self,
        prompt: dict[str, Any],
        video_id: str,
        *,
        url_a: str,
        result_b: dict[str, Any] | None = None,
        platform_token: str = "",
    ) -> None:
        ctx = self._prompt_video_context(prompt)
        segment_duration = ctx["segment_duration"]
        token = self._platform_token_for_video(video_id, platform_token)
        engine = self._video_engine_label()
        if result_b is None:
            first_frame_url_part_b = await self._ensure_first_frame(video_id, ctx, part="b")
            result_b = await self.video.generate(
                prompt=ctx["part_b"],
                duration_sec=segment_duration,
                aspect_ratio=ctx["aspect_ratio"],
                image_urls=ctx["image_urls"],
                first_frame_url=first_frame_url_part_b,
                voiceover_script=ctx["vo_b"],
                negative_prompt=ctx["negative"],
                voice_profile=ctx["voice_profile"],
                kit_constraint_text=ctx.get("kit_constraint_text", ""),
                brand=ctx.get("brand"),
                reference_video_urls=ctx.get("reference_video_urls"),
                product_reference_frames=bool(ctx.get("product_reference_frames")),
                progress_callback=self._make_seedance_progress_cb(video_id, "part_b", 50, 40),
                segment_label="part_b",
                platform_token=token,
                billing_biz_no=self._billing_biz_no(video_id, "part_b"),
            )
        if result_b.get("status") == "placeholder":
            seg = self._read_segment_json(video_id)
            seg["part_a"] = url_a
            if token:
                seg["platform_token"] = token
            self.repo.update_video(
                video_id,
                {
                    "output_status": "排队中",
                    "note": result_b.get("message", ""),
                    "segment_urls_json": json.dumps(seg, ensure_ascii=False),
                },
            )
            return
        if result_b.get("charge"):
            self._store_segment_charge(video_id, "part_b", result_b["charge"])
        url_b = result_b.get("video_url", "")
        if not url_a or not url_b:
            raise RuntimeError(f"{engine} 未返回完整分段视频 URL")
        await self._finalize_concat_video(
            prompt, video_id, url_a=url_a, url_b=url_b, segment_duration=segment_duration
        )

    async def recover_stuck_video(self, video_id: str) -> bool:
        """服务重启或轮询中断后，根据任务 ID 续跑（Seedance 或主站 AI Video）。"""
        video = self.repo.get_video(video_id)
        if not video or video.get("output_status") != "生成中":
            return False
        prompt = self.repo.get_prompt(video.get("prompt_id", ""))
        if not prompt:
            return False

        seg = self._read_segment_json(video_id)
        platform_token = self._platform_token_for_video(video_id)
        url_a = seg.get("part_a", "")
        engine = self._video_engine_label()
        if url_a:
            await self._complete_ai_video(
                prompt, video_id, url_a=url_a, platform_token=platform_token
            )
            return True

        progress = seg.get("progress") or {}
        task_id = progress.get("task_id", "")
        phase = progress.get("phase", "part_a")
        start_poll = int(progress.get("poll") or 0)
        provider = progress.get("provider") or (
            "platform" if self._use_platform_video() else "seedance"
        )

        if task_id:
            try:
                if provider == "platform":
                    remote = await self.video.get_platform_task(task_id, platform_token)
                else:
                    remote = await self.video.get_seedance_task(task_id)
            except Exception as exc:  # noqa: BLE001
                self.repo.update_video(
                    video_id,
                    {
                        "output_status": "失败",
                        "fail_reason": f"查询 {engine} 失败: {exc}",
                    },
                )
                return True

            remote_status = remote.get("status", "")
            if remote_status == "succeeded":
                url_a = (remote.get("content") or {}).get("video_url", "")
                if not url_a:
                    raise RuntimeError(f"{engine} 已成功但无 video_url")
                seg["part_a"] = url_a
                self.repo.update_video(
                    video_id,
                    {
                        "segment_urls_json": json.dumps(seg, ensure_ascii=False),
                        "note": f"已从 {engine} 恢复 Part A，继续 Part B…",
                    },
                )
                await self._complete_ai_video(
                    prompt, video_id, url_a=url_a, platform_token=platform_token
                )
                return True

            if remote_status in ("failed", "expired"):
                err = remote.get("error", {})
                msg = err.get("message") if isinstance(err, dict) else str(err)
                if provider == "platform":
                    charge = self._segment_charge(video_id, phase)
                    if charge:
                        from src.platform.billing import refund_video_charge

                        await refund_video_charge(
                            biz_no=str(charge.get("biz_no") or ""),
                            order_sn=str(charge.get("order_sn") or ""),
                        )
                self.repo.update_video(
                    video_id,
                    {"output_status": "失败", "fail_reason": msg or f"{engine} {remote_status}"},
                )
                return True

            if remote_status in ("running", "queued", "submitted") and phase == "part_a":
                part_charge = self._segment_charge(video_id, phase)
                if provider == "platform":
                    result_a = await self.video.resume_platform_task(
                        task_id,
                        platform_token,
                        progress_callback=self._make_seedance_progress_cb(
                            video_id, "part_a", 0, 50
                        ),
                        segment_label="part_a",
                        start_poll=start_poll,
                        billing_biz_no=str(
                            part_charge.get("biz_no")
                            or self._billing_biz_no(video_id, phase)
                        ),
                        charge_order_sn=str(part_charge.get("order_sn") or ""),
                    )
                else:
                    result_a = await self.video.resume_seedance_task(
                        task_id,
                        progress_callback=self._make_seedance_progress_cb(
                            video_id, "part_a", 0, 50
                        ),
                        segment_label="part_a",
                        start_poll=start_poll,
                    )
                seg["part_a"] = result_a.get("video_url", "")
                self.repo.update_video(
                    video_id,
                    {
                        "segment_urls_json": json.dumps(seg, ensure_ascii=False),
                        "note": f"{engine} · Part A 完成 · 开始 Part B (15-30s)…",
                    },
                )
                await self._complete_ai_video(
                    prompt,
                    video_id,
                    url_a=seg["part_a"],
                    platform_token=platform_token,
                )
                return True

        await self._generate_ai_video(prompt, video_id, platform_token=platform_token)
        return True

    async def recover_all_stuck_videos(self) -> list[str]:
        video_ids = [
            v["id"] for v in self.repo.list_videos() if v.get("output_status") == "生成中"
        ]
        if not video_ids:
            return []
        await asyncio.gather(
            *(self.recover_stuck_video(vid) for vid in video_ids),
            return_exceptions=True,
        )
        return video_ids

    async def _generate_ai_video(
        self, prompt: dict[str, Any], video_id: str, *, platform_token: str = ""
    ) -> None:
        ctx = self._prompt_video_context(prompt)
        single = self._is_single_segment_video(prompt)
        if not single and not ctx["part_b"]:
            raise ValueError("缺少 Part B prompt，无法生成 2×15s 成片")

        token = self._platform_token_for_video(video_id, platform_token)
        if token:
            self._store_platform_token(video_id, token)
        engine = self._video_engine_label()

        try:
            self._write_seedance_progress(
                video_id,
                phase="part_a",
                percent=0,
                seedance_status="pending",
                provider="platform" if self._use_platform_video() else "seedance",
                message=f"准备提交 {engine} Part A…",
            )
            self.repo.update_video(video_id, {"output_status": "生成中"})
            first_frame_url = await self._ensure_first_frame(video_id, ctx)
            result_a = await self.video.generate(
                prompt=ctx["part_a"],
                duration_sec=ctx["segment_duration"],
                aspect_ratio=ctx["aspect_ratio"],
                image_urls=ctx["image_urls"],
                first_frame_url=first_frame_url,
                voiceover_script=ctx["vo_a"],
                negative_prompt=ctx["negative"],
                voice_profile=ctx["voice_profile"],
                kit_constraint_text=ctx.get("kit_constraint_text", ""),
                brand=ctx.get("brand"),
                reference_video_urls=ctx.get("reference_video_urls"),
                product_reference_frames=bool(ctx.get("product_reference_frames")),
                progress_callback=self._make_seedance_progress_cb(video_id, "part_a", 0, 50),
                segment_label="part_a",
                platform_token=token,
                billing_biz_no=self._billing_biz_no(video_id, "part_a"),
            )
            if result_a.get("status") == "placeholder":
                self.repo.update_video(
                    video_id, {"output_status": "排队中", "note": result_a.get("message", "")}
                )
                return
            if result_a.get("charge"):
                self._store_segment_charge(video_id, "part_a", result_a["charge"])

            url_a = result_a.get("video_url", "")
            seg = self._read_segment_json(video_id)
            seg["part_a"] = url_a
            if token:
                seg["platform_token"] = token
            seg["progress"] = {
                **seg.get("progress", {}),
                "phase": "part_b",
                "percent": 50,
                "message": "Part A 完成，开始 Part B…",
                "updated_at": datetime.now(UTC).isoformat(),
            }
            self.repo.update_video(
                video_id,
                {
                    "output_status": "生成中",
                    "segment_urls_json": json.dumps(seg, ensure_ascii=False),
                    "note": (
                        f"{engine} · Part A 完成 · 单段收尾…"
                        if single
                        else f"{engine} · Part A 完成 · 开始 Part B (15-30s)…"
                    ),
                },
            )
            if single:
                await self._finalize_single_segment_video(
                    prompt,
                    video_id,
                    url_a=url_a,
                    segment_duration=ctx["segment_duration"],
                )
                return
            await self._complete_ai_video(
                prompt, video_id, url_a=url_a, platform_token=token
            )
        except Exception as exc:  # noqa: BLE001
            self.repo.update_video(video_id, {"output_status": "失败", "fail_reason": str(exc)})

    async def _create_manual_video(
        self,
        script_id: str,
        *,
        mode: str,
        prompt_id: str = "",
    ) -> None:
        video_id = f"V{script_id}-manual"
        if self.repo.get_video(video_id):
            return
        self.repo.create_video(
            {
                "id": video_id,
                "prompt_id": prompt_id,
                "script_id": script_id,
                "output_mode": mode,
                "output_status": "待剪辑",
                "note": "待剪辑同事二次剪辑；参考脚本与分镜",
            }
        )
