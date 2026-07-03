"""后期英文字幕烧录 — 正文白字黑边，品牌名黄字黑边且大一号。"""

import asyncio
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from src.pipeline.brand_profile import BrandProfile
from src.pipeline.video_concat import VIDEO_OUTPUT_DIR, ensure_video_dir

# 通用（与品牌无关）的上屏大小写保护词；品牌相关的还原/高亮由 BrandProfile 动态注入
_PROTECTED_TOKENS_BASE: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bafterpay\b", re.I), "AfterPay"),
    (re.compile(r"\btiktok\b", re.I), "TikTok"),
]

_BRAND_LITERALS_BASE: tuple[str, ...] = ()


def _protected_tokens(brand: BrandProfile | None) -> list[tuple[re.Pattern[str], str]]:
    """上屏大小写/拼写还原表：品牌发音→品牌拼写、品牌拼写大小写归一。"""
    toks: list[tuple[re.Pattern[str], str]] = []
    if brand is not None and brand.has_brand:
        name = brand.display
        if brand.has_pronunciation:
            pron = re.escape(brand.pronunciation.strip()).replace(r"\ ", r"\s*")
            toks.append((re.compile(rf"\b{pron}\b", re.I), name))
        toks.append((re.compile(rf"\b{re.escape(name)}\b", re.I), name))
    toks.extend(_PROTECTED_TOKENS_BASE)
    return toks


def _brand_literals(brand: BrandProfile | None) -> tuple[str, ...]:
    """需要黄字高亮的品牌词（品牌自身 + 通用品牌词）。"""
    lits = list(_BRAND_LITERALS_BASE)
    if brand is not None and brand.has_brand:
        lits.append(brand.display)
    return tuple(lits)


def _brand_split_re(literals: tuple[str, ...]) -> re.Pattern[str] | None:
    if not literals:
        return None
    return re.compile(
        "(" + "|".join(re.escape(t) for t in sorted(literals, key=len, reverse=True)) + ")"
    )

# 对标参考片：底部偏上约 1/5 处居中，大字粗黑边（9:16 @ 1920 高）
_BODY_FONT_SIZE = 72
_BRAND_FONT_SIZE = 88
_OUTLINE_WIDTH = 6
_MARGIN_H = 44
_MARGIN_V = 400  # Alignment=2 时距底边像素，约 20% 画面高度
_MAX_LINES = 2
_MAX_CHARS_PER_LINE = 22
_MIN_CUE_SEC = 0.75

_PRICE_RE = re.compile(r"\$\d[\d,]*(?:\.\d+)?")
_NUM_UNIT_RE = re.compile(
    r"\d+(?:\.\d+)?\s*(?:watt-hours?|kilowatt-hours?|watts?|amps?|volts?|wh|kwh)\b",
    re.I,
)

_ASS_HEADER = f"""[Script Info]
Title: Captions
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: CaptionBody,Arial Black,{_BODY_FONT_SIZE},&H00FFFFFF,&H00FFFFFF,&H00000000,&H96000000,-1,0,0,0,100,100,0,0,1,{_OUTLINE_WIDTH},0,2,{_MARGIN_H},{_MARGIN_H},{_MARGIN_V},1
Style: CaptionBrand,Arial Black,{_BRAND_FONT_SIZE},&H0000FFFF,&H0000FFFF,&H00000000,&H96000000,-1,0,0,0,100,100,0,0,1,{_OUTLINE_WIDTH},0,2,{_MARGIN_H},{_MARGIN_H},{_MARGIN_V},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def raw_video_path(video_id: str) -> Path:
    """无字幕的原始拼接成片（烧录字幕必须用此文件，避免二次烧录残留）。"""
    return VIDEO_OUTPUT_DIR / f"{video_id}.mp4"


def subtitled_video_path(video_id: str) -> Path:
    return VIDEO_OUTPUT_DIR / f"{video_id}_sub.mp4"


def resolve_burn_input_path(video_id: str, local_video_path: str | None = None) -> Path:
    raw = raw_video_path(video_id)
    if raw.is_file():
        return raw
    if local_video_path:
        p = Path(local_video_path)
        if p.is_file():
            return p
    raise FileNotFoundError(f"找不到无字幕源视频: {raw}")


def _parse_time_range(time_str: str) -> tuple[float, float]:
    raw = (time_str or "0-3s").strip().lower().replace(" ", "")
    m = re.match(r"(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)s?", raw)
    if not m:
        return 0.0, 3.0
    return float(m.group(1)), float(m.group(2))


def caption_source_text(item: dict[str, Any]) -> str:
    """上屏字幕必须与口播一致，优先用 spoken。"""
    return str(item.get("spoken") or item.get("voiceover") or item.get("display") or "")


def _sentence_case_line(line: str) -> str:
    """短视频字幕常用 Sentence case：句首大写，其余小写（品牌/型号由占位符保留）。"""
    s = line.strip()
    if not s:
        return s
    s = s.lower()
    for acro in ("rv", "ac", "dc", "usb", "tv", "wh", "kwh"):
        s = re.sub(rf"\b{re.escape(acro)}\b", acro.upper(), s)
    s = s[0].upper() + s[1:]
    s = re.sub(
        r'([.!?]["\']?)(\s+)([a-z])',
        lambda m: f"{m.group(1)}{m.group(2)}{m.group(3).upper()}",
        s,
    )
    s = re.sub(r"\bi\b", "I", s)
    return s


def format_subtitle_display(text: str, *, brand: BrandProfile | None = None) -> str:
    """品牌/型号正确大小写 + 正文 Sentence case（对标 TikTok 产品短视频字幕）。"""
    t = (text or "").strip()
    if not t:
        return ""
    placeholders: dict[str, str] = {}
    for pattern, replacement in _protected_tokens(brand):

        def _repl(_m: re.Match[str], rep: str = replacement) -> str:
            key = f"@@{len(placeholders)}@@"
            placeholders[key] = rep
            return key

        t = pattern.sub(_repl, t)
    if "\\N" in t:
        lines = [_sentence_case_line(ln) for ln in t.split("\\N")]
        t = "\\N".join(lines)
    else:
        t = _sentence_case_line(t)
    for key, value in placeholders.items():
        t = t.replace(key, value)
    return t


def _shield_phrases(text: str, brand: BrandProfile | None = None) -> tuple[str, list[str]]:
    phrases: list[str] = []
    t = text

    def keep(m: re.Match[str]) -> str:
        phrases.append(m.group(0))
        return f"\x01{len(phrases) - 1}\x01"

    for literal in sorted(_brand_literals(brand), key=len, reverse=True):
        t = re.sub(re.escape(literal), keep, t)
    t = _PRICE_RE.sub(keep, t)
    t = _NUM_UNIT_RE.sub(keep, t)
    return t, phrases


def _unshield_phrases(text: str, phrases: list[str]) -> str:
    out = text
    for i, phrase in enumerate(phrases):
        out = out.replace(f"\x01{i}\x01", phrase)
    return out


def _tokenize_for_wrap(text: str, brand: BrandProfile | None = None) -> list[str]:
    shielded, phrases = _shield_phrases(text, brand)
    return [_unshield_phrases(tok, phrases) for tok in shielded.split() if tok]


def _line_char_len(words: list[str]) -> int:
    if not words:
        return 0
    return sum(len(w) for w in words) + max(0, len(words) - 1)


def _pack_caption_blocks(
    tokens: list[str],
    *,
    max_chars: int = _MAX_CHARS_PER_LINE,
    max_lines: int = _MAX_LINES,
) -> list[str]:
    """每块严格最多 max_lines 行（至多 1 个 \\N）。"""
    blocks: list[str] = []
    block_lines: list[str] = []
    line_words: list[str] = []

    def flush_line() -> None:
        nonlocal line_words
        if not line_words:
            return
        block_lines.append(" ".join(line_words))
        line_words = []
        if len(block_lines) >= max_lines:
            blocks.append("\\N".join(block_lines))
            block_lines.clear()

    for token in tokens:
        projected = _line_char_len(line_words + [token])
        if line_words and projected > max_chars:
            flush_line()
        line_words.append(token)

    flush_line()
    if block_lines:
        blocks.append("\\N".join(block_lines[:max_lines]))
    return [b for b in blocks if b.strip()]


def _split_clauses(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+|\s*;\s*", text.strip())
    return [p.strip() for p in parts if p.strip()]


def split_display_into_captions(display: str, *, brand: BrandProfile | None = None) -> list[str]:
    if not display.strip():
        return []
    return _pack_caption_blocks(_tokenize_for_wrap(display, brand))


def _ass_time(seconds: float) -> str:
    seconds = max(0.0, seconds)
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def _escape_ass(text: str) -> str:
    return text.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")


def to_ass_rich_text(display: str, brand: BrandProfile | None = None) -> str:
    """白字正文 + 品牌黄字（\\r 显式切回样式）。"""
    if not display:
        return ""
    literals = _brand_literals(brand)
    split_re = _brand_split_re(literals)
    if split_re is None:
        return "{\\rCaptionBody}" + _escape_ass(display)
    parts = split_re.split(display)
    chunks: list[str] = ["{\\rCaptionBody}"]
    for part in parts:
        if not part:
            continue
        if part in literals:
            chunks.append(f"{{\\rCaptionBrand}}{_escape_ass(part)}{{\\rCaptionBody}}")
        else:
            chunks.append(_escape_ass(part))
    return "".join(chunks)


def _rich_multiline(block: str, brand: BrandProfile | None = None) -> str:
    lines = block.split("\\N")
    if len(lines) > _MAX_LINES:
        lines = lines[:_MAX_LINES]
    return "\\N".join(to_ass_rich_text(line, brand) for line in lines)


def _word_count(text: str) -> int:
    return max(1, len(text.replace("\\N", " ").split()))


def _schedule_blocks(
    blocks: list[str], start: float, end: float
) -> list[tuple[float, float, str]]:
    if not blocks:
        return []
    duration = max(end - start, _MIN_CUE_SEC)
    weights = [_word_count(b) for b in blocks]
    total = sum(weights)
    events: list[tuple[float, float, str]] = []
    t = start
    for i, block in enumerate(blocks):
        share = duration * weights[i] / total
        if i == len(blocks) - 1:
            b_end = end
        else:
            b_end = min(end, t + max(_MIN_CUE_SEC, share))
        events.append((t, b_end, block))
        t = b_end
    if events:
        events[-1] = (events[-1][0], end, events[-1][2])
    return events


def _normalize_voiceover_track(
    items: list[dict[str, Any]], brand: BrandProfile | None = None
) -> list[dict[str, Any]]:
    """把过长时间窗里的多句口播拆成多条，便于字幕与口播对齐。"""
    normalized: list[dict[str, Any]] = []
    for item in items:
        start, end = _parse_time_range(str(item.get("time", "")))
        duration = end - start
        spoken = caption_source_text(item)
        display = format_subtitle_display(spoken, brand=brand)
        clauses = _split_clauses(display) if display else []
        if duration <= 4.0 or len(clauses) <= 1:
            normalized.append(item)
            continue
        weights = [_word_count(c) for c in clauses]
        total = sum(weights) or 1
        t = start
        for idx, clause in enumerate(clauses):
            clause_end = end if idx == len(clauses) - 1 else t + duration * weights[idx] / total
            split_item = dict(item)
            split_item["spoken"] = clause
            split_item["time"] = f"{t:g}-{clause_end:g}s"
            if "display" in split_item:
                split_item["display"] = clause
            normalized.append(split_item)
            t = clause_end
    return normalized


def collect_heuristic_events(
    voiceover_a: list[dict[str, Any]],
    voiceover_b: list[dict[str, Any]],
    brand: BrandProfile | None = None,
) -> list[tuple[float, float, str]]:
    events: list[tuple[float, float, str]] = []
    track = _normalize_voiceover_track(voiceover_a, brand) + _normalize_voiceover_track(
        voiceover_b, brand
    )
    for item in track:
        events.extend(_expand_voiceover_events(item, brand))
    return events


def _expand_voiceover_events(
    item: dict[str, Any], brand: BrandProfile | None = None
) -> list[tuple[float, float, str]]:
    display = format_subtitle_display(caption_source_text(item), brand=brand)
    if not display:
        return []
    start, end = _parse_time_range(str(item.get("time", "")))
    if end <= start:
        end = start + 2.5
    blocks = split_display_into_captions(display, brand=brand)
    return _schedule_blocks(blocks, start, end)


def build_ass_from_events(
    events: list[tuple[float, float, str]],
    *,
    timing_mode: str = "tts_aligned",
    align_status: str = "TTS对齐",
    align_detail: str = "",
    brand: BrandProfile | None = None,
) -> tuple[str, str, str, str]:
    from src.pipeline.subtitle_align import events_to_ass_dialogues

    dialogues = events_to_ass_dialogues(events, brand=brand)
    if not dialogues:
        return "", timing_mode, align_status, align_detail
    return _ASS_HEADER + "\n".join(dialogues) + "\n", timing_mode, align_status, align_detail


def build_ass_content(
    voiceover_a: list[dict[str, Any]],
    voiceover_b: list[dict[str, Any]],
    *,
    video_path: str | Path | None = None,
    align: bool = True,
    tts_events: list[tuple[float, float, str]] | None = None,
    tts_detail: str = "",
    brand: BrandProfile | None = None,
) -> tuple[str, str, str, str]:
    """生成 ASS 正文；返回 (ass_text, timing_mode, align_status, align_detail)。"""
    from src.pipeline.subtitle_align import align_voiceover_to_video, events_to_ass_dialogues

    if tts_events:
        return build_ass_from_events(
            tts_events,
            timing_mode="tts_aligned",
            align_status="TTS对齐",
            align_detail=tts_detail or "字幕时间轴来自 TTS 词边界",
            brand=brand,
        )

    fallback = collect_heuristic_events(voiceover_a, voiceover_b, brand)
    timing_mode = "heuristic"
    align_status = "剧本估算"
    align_detail = "口播识别未启用"
    timed_events = fallback

    if align and video_path and fallback:
        result = align_voiceover_to_video(
            voiceover_a,
            voiceover_b,
            video_path,
            fallback_events=fallback,
            brand=brand,
        )
        timed_events = result.events
        timing_mode = result.timing_mode
        align_status = result.align_status
        align_detail = result.align_detail

    dialogues = events_to_ass_dialogues(timed_events, brand=brand)
    if not dialogues:
        return "", timing_mode, align_status, align_detail
    return _ASS_HEADER + "\n".join(dialogues) + "\n", timing_mode, align_status, align_detail


def _burn_with_ffmpeg(video_path: Path, ass_path: Path, output_path: Path) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("未找到 ffmpeg，无法烧录字幕")
    ass_escaped = ass_path.resolve().as_posix().replace(":", r"\:")
    vf = f"subtitles=filename='{ass_escaped}'"
    proc = subprocess.run(
        [ffmpeg, "-y", "-i", str(video_path), "-vf", vf, "-c:a", "copy", str(output_path)],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout or "ffmpeg 字幕烧录失败")[-800:])


async def burn_subtitles_on_video(
    local_video_path: str,
    *,
    voiceover_a: list[dict[str, Any]],
    voiceover_b: list[dict[str, Any]],
    video_id: str,
    tts_events: list[tuple[float, float, str]] | None = None,
    tts_detail: str = "",
    brand: BrandProfile | None = None,
) -> dict[str, str]:
    src = resolve_burn_input_path(video_id, local_video_path)
    ass_body, timing_mode, align_status, align_detail = await asyncio.to_thread(
        build_ass_content,
        voiceover_a,
        voiceover_b,
        video_path=src,
        align=tts_events is None,
        tts_events=tts_events,
        tts_detail=tts_detail,
        brand=brand,
    )
    if not ass_body.strip():
        return {"video_url": f"/uploads/videos/{src.name}", "skipped": True}

    ensure_video_dir()
    out_path = subtitled_video_path(video_id)

    with tempfile.TemporaryDirectory() as tmp:
        ass_path = Path(tmp) / "captions.ass"
        ass_path.write_text(ass_body, encoding="utf-8-sig")
        await asyncio.to_thread(_burn_with_ffmpeg, src, ass_path, out_path)

    return {
        "video_url": f"/uploads/videos/{out_path.name}",
        "local_path": str(out_path),
        "timing_mode": timing_mode,
        "subtitle_align_status": align_status,
        "subtitle_align_detail": align_detail,
    }
