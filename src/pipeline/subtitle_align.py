"""口播音频强制对齐 — 文案用剧本，时间戳来自 faster-whisper 词级识别。"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.config import ROOT, get_settings
from src.pipeline.brand_profile import BrandProfile
from src.pipeline.subtitles import (
    _MAX_LINES,
    _MIN_CUE_SEC,
    _normalize_voiceover_track,
    _parse_time_range,
    _rich_multiline,
    _schedule_blocks,
    _word_count,
    caption_source_text,
    format_subtitle_display,
    split_display_into_captions,
)

_ALIGN_PAD_START = 0.06
_ALIGN_PAD_END = 0.18
_MIN_MATCH_RATIO = 0.32
_ASR_LOOKAHEAD = 16

_model_lock = threading.Lock()
_model_cache: dict[str, Any] = {}


@dataclass
class TimedWord:
    word: str
    start: float
    end: float


@dataclass
class AlignResult:
    events: list[tuple[float, float, str]]
    timing_mode: str
    align_status: str
    align_detail: str


def describe_align_result(timing_mode: str) -> tuple[str, str]:
    if timing_mode == "audio_aligned":
        return "口播对齐", "已按识别到的口播时间轴烧录"
    if timing_mode == "energy_aligned":
        return "节奏对齐", "已按音频口播段落对齐（静音检测）"
    if timing_mode == "heuristic":
        return "剧本估算", "口播识别未启用"
    if timing_mode.startswith("heuristic_fallback:"):
        raw = timing_mode.split(":", 1)[1].strip()
        if any(k in raw for k in ("Hub", "LocalEntryNotFound", "ConnectError", "SSL")):
            return (
                "口播对齐失败",
                "Whisper 模型未下载或网络不可用，请运行: python scripts/download_whisper_model.py",
            )
        if any(k in raw for k in ("503", "whisper-1", "暂无可用")):
            return "口播对齐失败", "Whisper API 暂不可用；若未显示节奏对齐，请重烧字幕"
        if "no audio was received" in raw.lower():
            return (
                "口播对齐失败",
                "Edge TTS 未返回音频（音色服务异常），请点「重烧字幕」重试或换音色",
            )
        if any(k in raw for k in ("429", "quota", "Quota")):
            return "口播对齐失败", "Gemini 配额已用尽；若未显示节奏对齐，请重烧字幕"
        if "too_few_words" in raw:
            return "口播对齐失败", "视频中未识别到足够口播（可能几乎无旁白）"
        if "faster-whisper" in raw.lower():
            return "口播对齐失败", raw
        return "口播对齐失败", raw[:240]
    if timing_mode == "heuristic_mixed":
        return "剧本估算", "口播匹配率偏低，已回退剧本时间轴"
    return "剧本估算", timing_mode


def _configure_hf_env() -> Path:
    settings = get_settings()
    if settings.subtitle_whisper_hf_endpoint:
        os.environ.setdefault("HF_ENDPOINT", settings.subtitle_whisper_hf_endpoint)
    cache = ROOT / settings.subtitle_whisper_download_root
    cache.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("HF_HOME", str(cache))
    os.environ.setdefault("HUGGINGFACE_HUB_CACHE", str(cache / "hub"))
    return cache


def _default_modelscope_paths() -> list[Path]:
    settings = get_settings()
    ms_root = ROOT / settings.subtitle_whisper_download_root / "ms" / "Systran"
    return [
        ms_root / "faster-whisper-base___en",
        ms_root / "faster-whisper-base.en",
    ]


def _resolve_model_path() -> str:
    settings = get_settings()
    configured = settings.subtitle_whisper_model
    if configured and configured != "base.en":
        custom = Path(configured)
        if not custom.is_absolute():
            custom = ROOT / custom
        if custom.is_dir() and (custom / "model.bin").is_file():
            return str(custom)
    for candidate in _default_modelscope_paths():
        if candidate.is_dir() and (candidate / "model.bin").is_file():
            return str(candidate)
    bundled = ROOT / settings.subtitle_whisper_download_root / "base.en"
    if bundled.is_dir() and (bundled / "model.bin").is_file():
        return str(bundled)
    return configured or "base.en"


def _local_model_ready() -> bool:
    path = Path(_resolve_model_path())
    return path.is_dir() and (path / "model.bin").is_file()


def _get_whisper_model():
    settings = get_settings()
    model_path = _resolve_model_path()
    cache = _configure_hf_env()
    key = f"{model_path}:{settings.subtitle_whisper_device}:{settings.subtitle_whisper_compute_type}"
    with _model_lock:
        if key not in _model_cache:
            from faster_whisper import WhisperModel

            _model_cache[key] = WhisperModel(
                model_path,
                device=settings.subtitle_whisper_device,
                compute_type=settings.subtitle_whisper_compute_type,
                download_root=str(cache),
            )
        return _model_cache[key]


def _norm_token(token: str) -> str:
    return re.sub(r"[^a-z0-9$]", "", token.lower())


def _digits_only(token: str) -> str:
    return re.sub(r"\D", "", token)


def _parse_number(token: str) -> float | None:
    raw = token.strip().lstrip("$").replace(",", "")
    if not raw or not re.search(r"\d", raw):
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _numbers_close(script_token: str, heard_value: float, *, rel_tol: float = 0.08) -> bool:
    script_val = _parse_number(script_token)
    if script_val is None:
        return False
    if script_val == heard_value:
        return True
    if script_val == 0:
        return heard_value == 0
    return abs(script_val - heard_value) / max(abs(script_val), 1.0) <= rel_tol


def _asr_number_combo(
    asr_words: list[TimedWord], start: int, max_parts: int = 4
) -> tuple[float, int] | None:
    """将连续 ASR 数字碎片合并，如 2 + ,400 → 2400，13 + .4 → 13.4。"""
    parts: list[str] = []
    for j in range(start, min(start + max_parts, len(asr_words))):
        piece = asr_words[j].word.strip()
        if not piece:
            continue
        if parts and not re.search(r"[\d$.,]", piece):
            break
        if not re.search(r"\d", piece) and piece not in {".", ","}:
            break
        parts.append(piece)
        merged = "".join(parts).replace(",", "")
        val = _parse_number(merged)
        if val is not None:
            return val, j - start + 1
    return None


def _tokens_match(script: str, heard: str, brand: BrandProfile | None = None) -> bool:
    if not script or not heard:
        return False
    if script == heard:
        return True
    # 品牌发音模糊匹配（如 blue+tee ↔ bluetti），仅当产品有发音覆盖时启用
    if brand and brand.has_pronunciation:
        aliases = brand.alignment_aliases()
        spoken_tokens = brand.spoken_tokens()
        if aliases and script in aliases and heard in aliases:
            return True
        if spoken_tokens and script in spoken_tokens and heard in aliases:
            return True
        brand_lower = brand.display.lower()
        if brand_lower and brand_lower in {script, heard} and (script in aliases or heard in aliases):
            return True
    if len(script) >= 3 and (script in heard or heard in script):
        return True
    script_digits = _digits_only(script)
    heard_digits = _digits_only(heard)
    if script_digits and heard_digits:
        if script_digits == heard_digits:
            return True
        if len(script_digits) >= 3 and (
            script_digits.endswith(heard_digits) or heard_digits.endswith(script_digits)
        ):
            return True
    script_val = _parse_number(script)
    heard_val = _parse_number(heard)
    if script_val is not None and heard_val is not None and _numbers_close(script, heard_val):
        return True
    return False


def _spoken_words_for_item(
    item: dict[str, Any], brand: BrandProfile | None = None
) -> list[str]:
    spoken = str(item.get("spoken") or item.get("voiceover") or item.get("display") or "")
    if brand is not None:
        spoken = brand.apply_pronunciation(spoken)
    return [w for w in re.split(r"\s+", spoken.strip()) if w]


def _split_spoken_across_blocks(spoken_words: list[str], display_blocks: list[str]) -> list[list[str]]:
    if not display_blocks:
        return []
    if not spoken_words:
        return [[] for _ in display_blocks]
    weights = [_word_count(b.replace("\\N", " ")) for b in display_blocks]
    total = sum(weights) or len(display_blocks)
    chunks: list[list[str]] = []
    idx = 0
    for i, weight in enumerate(weights):
        remaining_blocks = len(weights) - i - 1
        remaining_words = len(spoken_words) - idx
        if i == len(weights) - 1:
            chunks.append(spoken_words[idx:])
            break
        take = max(1, round(remaining_words * weight / total))
        take = min(take, remaining_words - remaining_blocks)
        chunks.append(spoken_words[idx : idx + take])
        idx += take
    return chunks


def collect_voiceover_segments(
    voiceover_a: list[dict[str, Any]],
    voiceover_b: list[dict[str, Any]],
    brand: BrandProfile | None = None,
) -> list[dict[str, Any]]:
    """按分镜 time 窗口分组，避免把 CTA 字幕提前到 18–27s 空白之前。"""
    segments: list[dict[str, Any]] = []
    track = _normalize_voiceover_track(voiceover_a, brand) + _normalize_voiceover_track(
        voiceover_b, brand
    )
    for item in track:
        start, end = _parse_time_range(str(item.get("time", "")))
        if end <= start:
            end = start + 2.5
        caption = format_subtitle_display(caption_source_text(item), brand=brand)
        if not caption:
            continue
        caption_blocks = split_display_into_captions(caption, brand=brand)
        spoken_words = _spoken_words_for_item(item, brand=brand)
        spoken_chunks = _split_spoken_across_blocks(spoken_words, caption_blocks)
        blocks = [
            {
                "display": disp,
                "spoken_words": spoken_chunks[i] if i < len(spoken_chunks) else [],
            }
            for i, disp in enumerate(caption_blocks)
            if disp.strip()
        ]
        if blocks:
            segments.append({"start": start, "end": end, "blocks": blocks})
    return segments


def collect_blocks_with_spoken(
    voiceover_a: list[dict[str, Any]],
    voiceover_b: list[dict[str, Any]],
    brand: BrandProfile | None = None,
) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for seg in collect_voiceover_segments(voiceover_a, voiceover_b, brand):
        blocks.extend(seg["blocks"])
    return blocks


def _extract_audio_wav(video_path: Path, wav_path: Path) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("未找到 ffmpeg，无法提取音频")
    probe = subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-i",
            str(video_path),
        ],
        capture_output=True,
        text=True,
    )
    if "Audio:" not in (probe.stderr or "") and "audio" not in (probe.stderr or "").lower():
        raise RuntimeError("视频无音轨，无法做口播对齐（请开启 Seedance 原生配音）")
    proc = subprocess.run(
        [
            ffmpeg,
            "-y",
            "-i",
            str(video_path),
            "-vn",
            "-acodec",
            "pcm_s16le",
            "-ar",
            "16000",
            "-ac",
            "1",
            str(wav_path),
        ],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout or "音频提取失败")[-600:])


def _transcribe_words_local(wav_path: Path) -> list[TimedWord]:
    try:
        from faster_whisper import WhisperModel  # noqa: F401
    except ImportError as exc:
        raise RuntimeError("未安装 faster-whisper，请执行 pip install faster-whisper") from exc

    model = _get_whisper_model()
    segments, _info = model.transcribe(
        str(wav_path),
        language="en",
        word_timestamps=True,
        vad_filter=False,
        condition_on_previous_text=False,
    )
    return _words_from_segments(segments)


def _words_from_segments(segments) -> list[TimedWord]:
    words: list[TimedWord] = []
    for segment in segments:
        if getattr(segment, "words", None):
            for w in segment.words:
                token = (w.word or "").strip()
                if token:
                    words.append(TimedWord(token, float(w.start), float(w.end)))
            continue
        text = (getattr(segment, "text", None) or "").strip()
        if not text:
            continue
        parts = text.split()
        if not parts:
            continue
        seg_start = float(segment.start)
        seg_end = float(segment.end)
        step = max((seg_end - seg_start) / len(parts), 0.05)
        for i, part in enumerate(parts):
            words.append(TimedWord(part, seg_start + i * step, seg_start + (i + 1) * step))
    return words


def _resolve_whisper_api() -> tuple[str, str, str]:
    """返回 (api_key, base_url, 标签)。"""
    settings = get_settings()
    if settings.openai_api_key:
        base = settings.video_api_base or "https://api.openai.com/v1"
        return settings.openai_api_key, base.rstrip("/"), "openai"
    if settings.nuwa_api_key:
        return settings.nuwa_api_key, settings.nuwa_api_base.rstrip("/"), "nuwa"
    return "", "", ""


def _transcribe_words_api(wav_path: Path) -> list[TimedWord]:
    api_key, api_base, _label = _resolve_whisper_api()
    if not api_key:
        raise RuntimeError("未配置 OPENAI_API_KEY 或 NUWA_API_KEY，无法使用 Whisper API")
    from openai import OpenAI

    client = OpenAI(api_key=api_key, base_url=api_base)
    with wav_path.open("rb") as audio_file:
        response = client.audio.transcriptions.create(
            model="whisper-1",
            file=audio_file,
            language="en",
            response_format="verbose_json",
            timestamp_granularities=["word"],
        )
    words: list[TimedWord] = []
    for w in getattr(response, "words", None) or []:
        token = (getattr(w, "word", None) or "").strip()
        if token:
            words.append(TimedWord(token, float(w.start), float(w.end)))
    if words:
        return words
    for seg in getattr(response, "segments", None) or []:
        text = (getattr(seg, "text", None) or "").strip()
        if not text:
            continue
        parts = text.split()
        seg_start = float(getattr(seg, "start", 0))
        seg_end = float(getattr(seg, "end", seg_start + 1))
        step = max((seg_end - seg_start) / max(len(parts), 1), 0.05)
        for i, part in enumerate(parts):
            words.append(TimedWord(part, seg_start + i * step, seg_start + (i + 1) * step))
    if len(words) < 3:
        raise RuntimeError("Whisper API 未返回足够词级时间戳")
    return words


def _transcribe_words_gemini(wav_path: Path) -> list[TimedWord]:
    import base64
    import json

    from src.pipeline.gemini_client import gemini_configured, post_generate_content_sync

    settings = get_settings()
    if not gemini_configured(settings):
        raise RuntimeError("未配置 GEMINI_API_KEY 或 Vertex 凭据")

    audio_b64 = base64.b64encode(wav_path.read_bytes()).decode("ascii")
    model = settings.gemini_text_model or "gemini-2.0-flash"
    body = {
        "contents": [
            {
                "parts": [
                    {"inline_data": {"mime_type": "audio/wav", "data": audio_b64}},
                    {
                        "text": (
                            "Transcribe the English voiceover. Return JSON only:\n"
                            '{"words":[{"word":"hello","start":0.12,"end":0.34}]}\n'
                            "Rules: start/end in seconds; one item per spoken word in order; "
                            "cover the full clip; numbers and brand names as spoken."
                        )
                    },
                ]
            }
        ],
        "generationConfig": {
            "temperature": 0.1,
            "responseMimeType": "application/json",
        },
    }
    resp = post_generate_content_sync(settings, model, body)
    if resp.is_error:
        raise RuntimeError(resp.text[:300])
    data = resp.json()
    text = (
        data.get("candidates", [{}])[0]
        .get("content", {})
        .get("parts", [{}])[0]
        .get("text", "")
    )
    payload = json.loads(text.strip())
    words: list[TimedWord] = []
    for item in payload.get("words") or []:
        token = str(item.get("word") or "").strip()
        if token:
            words.append(TimedWord(token, float(item.get("start", 0)), float(item.get("end", 0))))
    if len(words) < 3:
        raise RuntimeError("Gemini 未返回足够词级时间戳")
    return words


def _transcribe_words(wav_path: Path) -> tuple[list[TimedWord], str]:
    settings = get_settings()
    provider = (settings.subtitle_align_provider or "auto").lower()
    errors: list[str] = []

    if provider in {"auto", "local"}:
        if provider == "local" or _local_model_ready():
            try:
                return _transcribe_words_local(wav_path), "local"
            except Exception as exc:  # noqa: BLE001
                errors.append(f"local:{exc}")
        elif provider == "auto":
            errors.append("local:本地 Whisper 模型未下载（可运行 python scripts/download_whisper_model.py）")

    if provider in {"auto", "api", "openai", "nuwa"}:
        try:
            words = _transcribe_words_api(wav_path)
            _, _, label = _resolve_whisper_api()
            return words, label
        except Exception as exc:  # noqa: BLE001
            errors.append(f"api:{exc}")

    if provider in {"auto", "gemini"}:
        try:
            return _transcribe_words_gemini(wav_path), "gemini"
        except Exception as exc:  # noqa: BLE001
            errors.append(f"gemini:{exc}")

    raise RuntimeError("；".join(errors) or "口播识别不可用")


def _match_script_word(
    script_words: list[str],
    i: int,
    asr_words: list[TimedWord],
    asr_idx: int,
    brand: BrandProfile | None = None,
) -> tuple[TimedWord, int] | None:
    """在 ASR 流中匹配 script_words[i]，返回 (时间词, 消耗的 ASR 词数)。"""
    target = _norm_token(script_words[i])
    if not target:
        return None

    end = min(asr_idx + _ASR_LOOKAHEAD, len(asr_words))
    for j in range(asr_idx, end):
        heard = _norm_token(asr_words[j].word)
        if _tokens_match(target, heard, brand):
            return asr_words[j], 1

        combo = _asr_number_combo(asr_words, j)
        if combo and _numbers_close(script_words[i], combo[0]):
            consumed = combo[1]
            return (
                TimedWord(
                    "".join(asr_words[k].word for k in range(j, j + consumed)),
                    asr_words[j].start,
                    asr_words[j + consumed - 1].end,
                ),
                consumed,
            )

        if "-" in script_words[i]:
            parts = [_norm_token(p) for p in script_words[i].split("-") if _norm_token(p)]
            if len(parts) >= 2 and j + len(parts) - 1 < len(asr_words):
                if all(
                    _tokens_match(parts[k], _norm_token(asr_words[j + k].word), brand)
                    for k in range(len(parts))
                ):
                    return (
                        TimedWord(
                            script_words[i],
                            asr_words[j].start,
                            asr_words[j + len(parts) - 1].end,
                        ),
                        len(parts),
                    )

        spoken_tokens = brand.spoken_tokens() if brand and brand.has_pronunciation else []
        if (
            i + 1 < len(script_words)
            and len(spoken_tokens) >= 2
            and target == spoken_tokens[0]
            and _norm_token(script_words[i + 1]) == spoken_tokens[1]
        ):
            aliases = brand.alignment_aliases() if brand else set()
            combo_text = heard
            consumed = 1
            if j + 1 < len(asr_words):
                combo_text = _norm_token(asr_words[j].word + asr_words[j + 1].word)
                consumed = 2
            if combo_text in aliases or _tokens_match(spoken_tokens[1], heard, brand):
                w = TimedWord(
                    f"{asr_words[j].word} {asr_words[j + 1].word if consumed > 1 else ''}".strip(),
                    asr_words[j].start,
                    asr_words[j + consumed - 1].end,
                )
                return w, consumed

    return None


def _interpolate_word_timings(
    timings: list[tuple[float, float] | None], direct: list[bool]
) -> list[tuple[float, float] | None]:
    known = [idx for idx, d in enumerate(direct) if d and timings[idx] is not None]
    if not known:
        return timings

    for a, b in zip(known, known[1:]):
        if b - a <= 1:
            continue
        t0 = timings[a]
        t1 = timings[b]
        if t0 is None or t1 is None:
            continue
        for k in range(a + 1, b):
            if direct[k]:
                continue
            frac = (k - a) / (b - a)
            start = t0[0] + (t1[0] - t0[0]) * frac
            end = t0[1] + (t1[1] - t0[1]) * frac
            timings[k] = (start, max(end, start + 0.04))

    first, last = known[0], known[-1]
    for idx in range(first):
        if timings[idx] is None:
            timings[idx] = timings[first]
    for idx in range(last + 1, len(timings)):
        if timings[idx] is None:
            timings[idx] = timings[last]
    return timings


def _align_script_to_asr(
    script_words: list[str],
    asr_words: list[TimedWord],
    brand: BrandProfile | None = None,
) -> list[tuple[float, float] | None]:
    if not script_words:
        return []
    if not asr_words:
        return [None] * len(script_words)

    timings: list[tuple[float, float] | None] = [None] * len(script_words)
    direct = [False] * len(script_words)
    asr_idx = 0
    i = 0
    spoken_tokens = brand.spoken_tokens() if brand and brand.has_pronunciation else []
    while i < len(script_words):
        hit = _match_script_word(script_words, i, asr_words, asr_idx, brand)
        if hit is None:
            i += 1
            continue

        w, consumed = hit
        timings[i] = (w.start, w.end)
        direct[i] = True
        asr_idx += consumed

        if (
            i + 1 < len(script_words)
            and len(spoken_tokens) >= 2
            and _norm_token(script_words[i]) == spoken_tokens[0]
            and _norm_token(script_words[i + 1]) == spoken_tokens[1]
            and consumed >= 2
        ):
            timings[i + 1] = (w.start, w.end)
            direct[i + 1] = True
            i += 2
            continue

        i += 1

    return _interpolate_word_timings(timings, direct)


def _block_time_from_words(
    word_times: list[tuple[float, float]], fallback: tuple[float, float] | None = None
) -> tuple[float, float] | None:
    if word_times:
        start = max(0.0, word_times[0][0] - _ALIGN_PAD_START)
        end = word_times[-1][1] + _ALIGN_PAD_END
        if end - start < _MIN_CUE_SEC:
            end = start + _MIN_CUE_SEC
        return start, end
    return fallback


def _events_differ(
    aligned: list[tuple[float, float, str]], fallback: list[tuple[float, float, str]] | None
) -> bool:
    if not fallback or len(aligned) != len(fallback):
        return bool(aligned)
    for (a0, a1, at), (f0, f1, ft) in zip(aligned, fallback):
        if at != ft:
            return True
        if abs(a0 - f0) > 0.15 or abs(a1 - f1) > 0.15:
            return True
    return False


def _block_weights(blocks_meta: list[dict[str, Any]]) -> list[int]:
    weights: list[int] = []
    for block in blocks_meta:
        spoken = block.get("spoken_words") or []
        weight = len(spoken) or _word_count(str(block["display"]).replace("\\N", " "))
        weights.append(max(1, weight))
    return weights


def _schedule_blocks_in_span(
    blocks_meta: list[dict[str, Any]],
    span_start: float,
    span_end: float,
    *,
    fallback_events: list[tuple[float, float, str]] | None = None,
) -> list[tuple[float, float, str]]:
    if not blocks_meta or span_end - span_start < 0.25:
        return fallback_events or []

    weights = _block_weights(blocks_meta)
    total = sum(weights)
    events: list[tuple[float, float, str]] = []
    cursor = span_start
    span = span_end - span_start

    for i, block in enumerate(blocks_meta):
        display = str(block["display"])
        if i == len(blocks_meta) - 1:
            start = max(0.0, cursor - _ALIGN_PAD_START)
            end = span_end + _ALIGN_PAD_END
        else:
            share = span * weights[i] / total
            start = max(0.0, cursor - _ALIGN_PAD_START)
            end = cursor + share + _ALIGN_PAD_END
            cursor += share
        if end - start < _MIN_CUE_SEC:
            end = start + _MIN_CUE_SEC
        events.append((start, end, display))

    if fallback_events and not _events_differ(events, fallback_events):
        return fallback_events
    return events


def align_caption_events(
    blocks_meta: list[dict[str, Any]],
    asr_words: list[TimedWord],
    *,
    fallback_events: list[tuple[float, float, str]] | None = None,
    brand: BrandProfile | None = None,
) -> tuple[list[tuple[float, float, str]], float]:
    if not blocks_meta:
        return [], 0.0

    script_words: list[str] = []
    ranges: list[tuple[int, int, str]] = []
    for block in blocks_meta:
        chunk = block.get("spoken_words") or []
        start = len(script_words)
        script_words.extend(str(w) for w in chunk)
        ranges.append((start, len(script_words), str(block["display"])))

    aligned = _align_script_to_asr(script_words, asr_words, brand)
    matched_words = sum(1 for t in aligned if t is not None)
    word_ratio = matched_words / max(len(script_words), 1)

    events: list[tuple[float, float, str]] = []
    matched_blocks = 0

    for i, (start_i, end_i, display) in enumerate(ranges):
        fallback = fallback_events[i] if fallback_events and i < len(fallback_events) else None
        if start_i >= end_i:
            if fallback:
                events.append((fallback[0], fallback[1], display))
            continue
        word_times = [t for t in aligned[start_i:end_i] if t is not None]
        if word_times and (word_times[-1][1] - word_times[0][0]) >= 0.08:
            matched_blocks += 1
        timing = _block_time_from_words(
            word_times,
            fallback=(fallback[0], fallback[1]) if fallback else None,
        )
        if timing is None:
            continue
        events.append((timing[0], timing[1], display))

    if not events:
        return fallback_events or [], 0.0

    block_ratio = matched_blocks / max(len(ranges), 1)
    ratio = min(word_ratio, block_ratio)

    if ratio < _MIN_MATCH_RATIO and asr_words:
        span_start = max(0.0, asr_words[0].start - _ALIGN_PAD_START)
        span_end = asr_words[-1].end + _ALIGN_PAD_END
        proportional = _schedule_blocks_in_span(
            blocks_meta, span_start, span_end, fallback_events=fallback_events
        )
        if proportional and (not fallback_events or _events_differ(proportional, fallback_events)):
            return proportional, block_ratio

    if ratio < _MIN_MATCH_RATIO and fallback_events:
        return fallback_events, ratio
    if fallback_events and not _events_differ(events, fallback_events):
        return fallback_events, ratio
    return events, ratio


def _audio_duration(wav_path: Path) -> float:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return 30.0
    proc = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(wav_path),
        ],
        capture_output=True,
        text=True,
    )
    try:
        return float((proc.stdout or "30").strip())
    except ValueError:
        return 30.0


def _detect_speech_regions(wav_path: Path) -> list[tuple[float, float]]:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return []
    proc = subprocess.run(
        [
            ffmpeg,
            "-i",
            str(wav_path),
            "-af",
            "silencedetect=noise=-32dB:d=0.28",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
    )
    silences: list[tuple[float, float]] = []
    pending_start: float | None = None
    for line in (proc.stderr or "").splitlines():
        if "silence_start:" in line:
            m = re.search(r"silence_start:\s*([\d.]+)", line)
            if m:
                pending_start = float(m.group(1))
        elif "silence_end:" in line and pending_start is not None:
            m = re.search(r"silence_end:\s*([\d.]+)", line)
            if m:
                silences.append((pending_start, float(m.group(1))))
                pending_start = None

    duration = _audio_duration(wav_path)
    regions: list[tuple[float, float]] = []
    cursor = 0.0
    for s_start, s_end in silences:
        if s_start > cursor + 0.12:
            regions.append((cursor, s_start))
        cursor = s_end
    if duration > cursor + 0.12:
        regions.append((cursor, duration))

    merged: list[tuple[float, float]] = []
    for region in regions:
        if merged and region[0] - merged[-1][1] < 0.2:
            merged[-1] = (merged[-1][0], region[1])
        elif region[1] - region[0] >= 0.35:
            merged.append(region)
    return merged


def _intersect_regions(
    regions: list[tuple[float, float]], window_start: float, window_end: float
) -> list[tuple[float, float]]:
    clipped: list[tuple[float, float]] = []
    for start, end in regions:
        a = max(start, window_start)
        b = min(end, window_end)
        if b - a >= 0.2:
            clipped.append((a, b))
    return clipped


def _asr_words_in_window(words: list[TimedWord], start: float, end: float) -> list[TimedWord]:
    return [w for w in words if w.end > start - 0.15 and w.start < end + 0.15]


def _segment_spoken_words(seg: dict[str, Any]) -> list[str]:
    spoken: list[str] = []
    for block in seg.get("blocks") or []:
        spoken.extend(str(w) for w in (block.get("spoken_words") or []))
    return spoken


def _window_covers_anchor(
    window_words: list[TimedWord], anchor: str, brand: BrandProfile | None = None
) -> bool:
    if not anchor:
        return True
    for w in window_words[:8]:
        if _tokens_match(anchor, _norm_token(w.word), brand):
            return True
    return False


def _asr_words_for_segment(
    seg: dict[str, Any],
    asr_words: list[TimedWord],
    *,
    search_from: float = 0.0,
    brand: BrandProfile | None = None,
) -> list[TimedWord]:
    """优先用分镜时间窗；CTA 等标在 27s 但口播在 21s 时，按 spoken 首词全局搜索。"""
    window_words = _asr_words_in_window(asr_words, seg["start"], seg["end"])
    spoken = _segment_spoken_words(seg)
    if not spoken:
        return window_words

    anchor = _norm_token(spoken[0])
    if len(window_words) >= 2 and _window_covers_anchor(window_words, anchor, brand):
        return window_words

    anchor_from = max(search_from, seg["start"] - 6.0)
    anchor_idx: int | None = None
    for j, w in enumerate(asr_words):
        if w.start < anchor_from - 0.2:
            continue
        if _tokens_match(anchor, _norm_token(w.word), brand):
            anchor_idx = j
            break

    if anchor_idx is None:
        return window_words

    tail = _norm_token(spoken[-1])
    end_idx = anchor_idx
    limit = min(anchor_idx + max(len(spoken) + 8, 12), len(asr_words))
    for j in range(anchor_idx, limit):
        end_idx = j
        if _tokens_match(tail, _norm_token(asr_words[j].word), brand):
            break
    return asr_words[anchor_idx : end_idx + 1]


def align_segments_to_asr_words(
    segments: list[dict[str, Any]],
    asr_words: list[TimedWord],
    *,
    fallback_events: list[tuple[float, float, str]] | None = None,
    brand: BrandProfile | None = None,
) -> tuple[list[tuple[float, float, str]], float]:
    events: list[tuple[float, float, str]] = []
    fb_idx = 0
    used_asr = False
    fallback = fallback_events or []
    search_from = 0.0
    matched_segments = 0

    for seg in segments:
        n_blocks = len(seg["blocks"])
        seg_fallback = fallback[fb_idx : fb_idx + n_blocks]
        fb_idx += n_blocks
        window_words = _asr_words_for_segment(
            seg, asr_words, search_from=search_from, brand=brand
        )
        if len(window_words) >= 2:
            seg_events, match_ratio = align_caption_events(
                seg["blocks"],
                window_words,
                fallback_events=seg_fallback or None,
                brand=brand,
            )
            if seg_events and match_ratio >= _MIN_MATCH_RATIO and (
                not seg_fallback or _events_differ(seg_events, seg_fallback)
            ):
                used_asr = True
                matched_segments += 1
                events.extend(seg_events)
                search_from = max(search_from, window_words[-1].end)
                continue
            if window_words and seg["blocks"]:
                span_start = window_words[0].start - _ALIGN_PAD_START
                span_end = window_words[-1].end + _ALIGN_PAD_END
                proportional = _schedule_blocks_in_span(
                    seg["blocks"],
                    max(0.0, span_start),
                    span_end,
                    fallback_events=seg_fallback or None,
                )
                if proportional and (
                    not seg_fallback or _events_differ(proportional, seg_fallback)
                ):
                    used_asr = True
                    matched_segments += 1
                    events.extend(proportional)
                    search_from = max(search_from, window_words[-1].end)
                    continue
        if seg_fallback:
            events.extend(seg_fallback)
        else:
            for block in seg["blocks"]:
                events.extend(_schedule_blocks([block["display"]], seg["start"], seg["end"]))

    if not events:
        return fallback_events or [], 0.0
    if fallback_events and not used_asr:
        return fallback_events, 0.0
    ratio = matched_segments / max(len(segments), 1)
    return _smooth_event_timings(events), ratio


def align_segments_to_speech_regions(
    segments: list[dict[str, Any]],
    regions: list[tuple[float, float]],
    *,
    fallback_events: list[tuple[float, float, str]] | None = None,
) -> list[tuple[float, float, str]]:
    events: list[tuple[float, float, str]] = []
    fb_idx = 0
    used_energy = False
    fallback = fallback_events or []

    for seg in segments:
        n_blocks = len(seg["blocks"])
        seg_fallback = fallback[fb_idx : fb_idx + n_blocks]
        fb_idx += n_blocks
        window_regions = _intersect_regions(regions, seg["start"], seg["end"])

        if window_regions:
            seg_events = align_blocks_to_speech_regions(
                seg["blocks"], window_regions, fallback_events=seg_fallback or None
            )
            if seg_events and (not seg_fallback or _events_differ(seg_events, seg_fallback)):
                used_energy = True
                events.extend(seg_events)
                continue

        if seg_fallback:
            events.extend(seg_fallback)
        else:
            for block in seg["blocks"]:
                events.extend(_schedule_blocks([block["display"]], seg["start"], seg["end"]))

    if not events:
        return fallback_events or []
    if fallback_events and not used_energy:
        return fallback_events
    return _smooth_event_timings(events)


def align_blocks_to_speech_regions(
    blocks_meta: list[dict[str, Any]],
    regions: list[tuple[float, float]],
    *,
    fallback_events: list[tuple[float, float, str]] | None = None,
) -> list[tuple[float, float, str]]:
    if not blocks_meta or not regions:
        return fallback_events or []

    weights = [_word_count(str(b["display"]).replace("\\N", " ")) for b in blocks_meta]
    total_weight = sum(weights) or len(blocks_meta)
    total_speech = sum(end - start for start, end in regions)
    if total_speech < 2.0:
        return fallback_events or []

    timeline: list[tuple[float, float]] = []
    for start, end in regions:
        t = start
        while t < end - 0.05:
            timeline.append((t, min(end, t + 0.05)))
            t += 0.05

    events: list[tuple[float, float, str]] = []
    cursor = 0
    for i, block in enumerate(blocks_meta):
        share = max(1, round(len(timeline) * weights[i] / total_weight))
        if i == len(blocks_meta) - 1:
            chunk = timeline[cursor:]
        else:
            chunk = timeline[cursor : cursor + share]
            cursor += share
        if not chunk:
            continue
        start = max(0.0, chunk[0][0] - _ALIGN_PAD_START)
        end = chunk[-1][1] + _ALIGN_PAD_END
        if end - start < _MIN_CUE_SEC:
            end = start + _MIN_CUE_SEC
        events.append((start, end, str(block["display"])))

    if not events or (fallback_events and not _events_differ(events, fallback_events)):
        return fallback_events or events
    return _smooth_event_timings(events)


def _prepare_wav(video_path: str | Path) -> tuple[tempfile.TemporaryDirectory, Path]:
    tmp = tempfile.TemporaryDirectory()
    wav_path = Path(tmp.name) / "align.wav"
    _extract_audio_wav(Path(video_path), wav_path)
    return tmp, wav_path


def transcribe_video_words(video_path: str | Path) -> tuple[list[TimedWord], str]:
    video = Path(video_path)
    if not video.is_file():
        raise FileNotFoundError(f"视频不存在: {video}")
    tmp, wav_path = _prepare_wav(video)
    with tmp:
        return _transcribe_words(wav_path)


def align_voiceover_to_video(
    voiceover_a: list[dict[str, Any]],
    voiceover_b: list[dict[str, Any]],
    video_path: str | Path,
    *,
    fallback_events: list[tuple[float, float, str]] | None = None,
    brand: BrandProfile | None = None,
) -> AlignResult:
    settings = get_settings()
    if not settings.subtitle_align_enabled:
        status, detail = describe_align_result("heuristic")
        return AlignResult(fallback_events or [], "heuristic", status, detail)

    blocks_meta = collect_blocks_with_spoken(voiceover_a, voiceover_b, brand)
    if not blocks_meta:
        status, detail = describe_align_result("heuristic")
        return AlignResult(fallback_events or [], "heuristic", status, detail)

    video = Path(video_path)
    if not video.is_file():
        status, detail = describe_align_result("heuristic")
        return AlignResult(fallback_events or [], "heuristic", status, detail)

    tmp, wav_path = _prepare_wav(video)
    with tmp:
        asr_error = ""
        try:
            asr_words, asr_engine = _transcribe_words(wav_path)
            video_duration = _audio_duration(wav_path)
            if len(asr_words) >= 3:
                segments = collect_voiceover_segments(voiceover_a, voiceover_b, brand)
                events, _match_ratio = align_segments_to_asr_words(
                    segments, asr_words, fallback_events=fallback_events, brand=brand
                )
                if events and fallback_events and _events_differ(events, fallback_events):
                    events = _smooth_event_timings(events)
                    events = _extend_tail_events(
                        events, video_duration=video_duration, asr_words=asr_words
                    )
                    status, detail = describe_align_result("audio_aligned")
                    engine_label = {
                        "openai": "OpenAI Whisper",
                        "nuwa": "Nuwa Whisper",
                        "gemini": "Gemini",
                        "local": "本地 Whisper",
                    }.get(asr_engine, asr_engine)
                    detail = (
                        f"{detail}（{engine_label} · {len(asr_words)} 词 · "
                        f"{len(events)} 条字幕）"
                    )
                    return AlignResult(events, "audio_aligned", status, detail)
        except Exception as exc:  # noqa: BLE001
            asr_error = str(exc)

        regions = _detect_speech_regions(wav_path)
        segments = collect_voiceover_segments(voiceover_a, voiceover_b, brand)
        video_duration = _audio_duration(wav_path)
        if len(regions) >= 1 and segments:
            energy_events = align_segments_to_speech_regions(
                segments, regions, fallback_events=fallback_events
            )
            if energy_events and fallback_events and _events_differ(energy_events, fallback_events):
                energy_events = _extend_tail_events(
                    energy_events, video_duration=video_duration
                )
                status, detail = describe_align_result("energy_aligned")
                speech_sec = sum(e - s for s, e in regions)
                detail = (
                    f"{detail}（{len(regions)} 段口播 · 共 {speech_sec:.1f}s · "
                    f"{len(segments)} 个分镜窗 · {len(energy_events)} 条字幕）"
                )
                return AlignResult(energy_events, "energy_aligned", status, detail)

    if asr_error:
        mode = f"heuristic_fallback:{asr_error}"
        status, detail = describe_align_result(mode)
        return AlignResult(fallback_events or [], mode, status, detail)

    status, detail = describe_align_result("heuristic_mixed")
    return AlignResult(fallback_events or [], "heuristic_mixed", status, detail)


def _extend_tail_events(
    events: list[tuple[float, float, str]],
    *,
    video_duration: float,
    asr_words: list[TimedWord] | None = None,
) -> list[tuple[float, float, str]]:
    if not events:
        return events
    tail_end = video_duration
    if asr_words:
        tail_end = max(tail_end, asr_words[-1].end + _ALIGN_PAD_END)
    start, end, text = events[-1]
    if end < tail_end - 0.15:
        events[-1] = (start, min(tail_end, end + 0.5), text)
    return events


def _smooth_event_timings(events: list[tuple[float, float, str]]) -> list[tuple[float, float, str]]:
    if not events:
        return []
    ordered = sorted(events, key=lambda e: e[0])
    smoothed: list[tuple[float, float, str]] = []
    for start, end, text in ordered:
        start = max(0.0, start)
        end = max(end, start + _MIN_CUE_SEC)
        if smoothed and start < smoothed[-1][1]:
            prev_start, prev_end, prev_text = smoothed[-1]
            split = (prev_end + start) / 2
            smoothed[-1] = (prev_start, max(prev_start + _MIN_CUE_SEC, split - 0.04), prev_text)
            start = max(start, smoothed[-1][1] + 0.02)
            end = max(end, start + _MIN_CUE_SEC)
        smoothed.append((start, end, text))
    return smoothed


def events_to_ass_dialogues(
    events: list[tuple[float, float, str]],
    brand: BrandProfile | None = None,
) -> list[str]:
    from src.pipeline.subtitles import _ass_time

    dialogues: list[str] = []
    for start, end, block in events:
        if end <= start:
            end = start + _MIN_CUE_SEC
        line_count = block.count("\\N") + 1
        if line_count > _MAX_LINES:
            continue
        rich = _rich_multiline(block, brand)
        dialogues.append(
            f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},CaptionBody,,0,0,0,,{rich}"
        )
    return dialogues
