"""TTS 后期口播 — 先自然语速生成音频，再按词边界对齐字幕。"""

from __future__ import annotations

import asyncio
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.config import get_settings
from src.pipeline.audio_mux import (
    mix_delayed_segments,
    mp3_to_wav,
    replace_video_audio,
    tempo_wav,
)
from src.pipeline.subtitle_align import (
    _audio_duration,
    _norm_token,
    _split_spoken_across_blocks,
    _spoken_words_for_item,
    _tokens_match,
)
from src.pipeline.subtitles import (
    _MIN_CUE_SEC,
    caption_source_text,
    format_subtitle_display,
    split_display_into_captions,
)
from src.pipeline.brand_profile import BrandProfile
from src.pipeline.voice_persona import iter_tts_voice_candidates, resolve_tts_voice

_ALIGN_PAD_START = 0.05
_ALIGN_PAD_END = 0.16
_TICKS_PER_SEC = 10_000_000


@dataclass
class TtsWord:
    text: str
    start: float
    end: float


@dataclass
class TtsSegmentResult:
    global_start: float
    spoken: str
    display_blocks: list[str]
    spoken_chunks: list[list[str]]
    words: list[TtsWord] = field(default_factory=list)
    wav_path: Path | None = None
    audio_duration: float = 0.0


@dataclass
class TtsPostResult:
    video_path: Path
    events: list[tuple[float, float, str]]
    provider: str
    voice: str
    segment_count: int
    detail: str


def _tts_input_text(
    item: dict[str, Any],
    *,
    language: str | None = None,
    brand: BrandProfile | None = None,
) -> str:
    from src.pipeline.workflow_language import is_spanish

    spoken = caption_source_text(item)
    if is_spanish(language):
        return spoken.strip()
    # 把品牌拼写改写成发音（如 BLUETTI→"blue tee"）；无发音覆盖时不改动
    if brand is not None:
        spoken = brand.apply_pronunciation(spoken)
    return spoken.strip()


def pick_tts_voice(
    voice_profile: dict[str, Any] | None,
    *,
    account: dict[str, Any] | None = None,
    account_id: str = "",
    override: str = "",
    language: str | None = None,
) -> str:
    return resolve_tts_voice(
        voice_profile,
        account=account,
        account_id=account_id,
        override=override,
        language=language,
    )


def _parse_time_range(time_str: str) -> tuple[float, float]:
    raw = (time_str or "0-3s").strip().lower().replace(" ", "")
    m = re.match(r"(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)s?", raw)
    if not m:
        return 0.0, 3.0
    return float(m.group(1)), float(m.group(2))


def _words_from_audio_duration(text: str, duration: float) -> list[TtsWord]:
    tokens = [t for t in re.split(r"(\s+)", text) if t and not t.isspace()]
    if not tokens:
        return []
    weights = [max(len(re.sub(r"\W", "", t)), 1) for t in tokens]
    total = sum(weights) or 1
    words: list[TtsWord] = []
    cursor = 0.0
    for token, weight in zip(tokens, weights):
        slot = duration * weight / total
        words.append(TtsWord(token, cursor, cursor + slot))
        cursor += slot
    return words


def _is_no_audio_tts_error(exc: BaseException) -> bool:
    name = type(exc).__name__
    msg = str(exc).lower()
    return name == "NoAudioReceived" or "no audio was received" in msg


async def _synthesize_edge(text: str, voice: str, mp3_path: Path) -> list[TtsWord]:
    import edge_tts

    settings = get_settings()
    communicate = edge_tts.Communicate(
        text,
        voice,
        boundary="WordBoundary",
        rate=settings.tts_rate or "+0%",
    )
    words: list[TtsWord] = []
    with mp3_path.open("wb") as audio_file:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_file.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                start = float(chunk["offset"]) / _TICKS_PER_SEC
                end = start + float(chunk["duration"]) / _TICKS_PER_SEC
                token = str(chunk.get("text") or "").strip()
                if token:
                    words.append(TtsWord(token, start, end))
    if not words and mp3_path.is_file():
        duration = _audio_duration(mp3_path)
        words = _words_from_audio_duration(text, duration)
    return words


async def _synthesize_edge_with_fallback(
    text: str,
    voice_candidates: list[str],
    mp3_path: Path,
) -> tuple[list[TtsWord], str]:
    errors: list[str] = []
    for voice in voice_candidates:
        try:
            return await _synthesize_edge(text, voice, mp3_path), voice
        except Exception as exc:  # noqa: BLE001
            if _is_no_audio_tts_error(exc):
                errors.append(f"{voice}:无音频")
                continue
            raise
    detail = "；".join(errors) or "未知错误"
    raise RuntimeError(
        f"Edge TTS 全部音色失败（已尝试 {len(voice_candidates)} 个）: {detail}"
    )


async def _synthesize_segment(
    text: str,
    voice_candidates: list[str],
    work_dir: Path,
    tag: str,
) -> tuple[Path, list[TtsWord], float, str]:
    """自然语速合成，不按分镜时间窗变速或裁剪。"""
    mp3 = work_dir / f"{tag}.mp3"
    wav = work_dir / f"{tag}.wav"
    words, voice_used = await _synthesize_edge_with_fallback(text, voice_candidates, mp3)
    if not mp3.is_file() or mp3.stat().st_size < 64:
        raise RuntimeError(f"TTS 未生成音频: {text[:40]}…")
    mp3_to_wav(mp3, wav)
    duration = _audio_duration(wav)
    if words:
        duration = max(duration, words[-1].end + 0.04)
    return wav, words, duration, voice_used


def _collect_tts_items(
    voiceover_a: list[dict[str, Any]],
    voiceover_b: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in list(voiceover_a) + list(voiceover_b):
        spoken = caption_source_text(item).strip().lower()
        if not spoken or spoken in seen:
            continue
        seen.add(spoken)
        items.append(item)
    items.sort(key=lambda it: _parse_time_range(str(it.get("time", "")))[0])
    return items


def _schedule_segments_sequential(
    segments: list[TtsSegmentResult],
    *,
    gap_sec: float,
) -> list[TtsSegmentResult]:
    """按台词顺序首尾相接铺时间轴，global_start 由实际音频时长决定。"""
    cursor = 0.0
    scheduled: list[TtsSegmentResult] = []
    for seg in segments:
        scheduled.append(
            TtsSegmentResult(
                global_start=cursor,
                spoken=seg.spoken,
                display_blocks=seg.display_blocks,
                spoken_chunks=seg.spoken_chunks,
                words=seg.words,
                wav_path=seg.wav_path,
                audio_duration=seg.audio_duration,
            )
        )
        cursor += max(seg.audio_duration, 0.1) + gap_sec
    return scheduled


def _token_close(a: str, b: str) -> bool:
    if not a or not b:
        return False
    if len(a) >= 3 and (a in b or b in a):
        return True
    return _digits_only(a) and _digits_only(b) and (
        _digits_only(a) == _digits_only(b)
        or _digits_only(a).endswith(_digits_only(b))
        or _digits_only(b).endswith(_digits_only(a))
    )


def _digits_only(token: str) -> str:
    return re.sub(r"\D", "", token)


def _group_words_by_pause(words: list[TtsWord], *, gap: float) -> list[list[TtsWord]]:
    """按 TTS 词间停顿与句末标点切分短语，作为字幕断句依据。"""
    if not words:
        return []
    groups: list[list[TtsWord]] = [[words[0]]]
    for word in words[1:]:
        prev = groups[-1][-1]
        pause = word.start - prev.end
        if pause >= gap or re.search(r"[.!?]$", prev.text.strip()):
            groups.append([word])
        elif pause >= gap * 0.55 and re.search(r"[,;:]$", prev.text.strip()):
            groups.append([word])
        else:
            groups[-1].append(word)
    return groups


def _consume_words_for_block(
    block: str, words: list[TtsWord], start: int
) -> tuple[list[TtsWord], int]:
    """把一屏字幕文案模糊匹配到 TTS 词序列，返回匹配词与下一起始下标。"""
    block_tokens = [t for t in block.replace("\\N", " ").split() if t]
    if not block_tokens or start >= len(words):
        return [], start

    matched: list[TtsWord] = []
    wi = start
    for bt in block_tokens:
        target = _norm_token(bt)
        if not target:
            continue
        found = False
        for j in range(wi, min(wi + 10, len(words))):
            heard = _norm_token(words[j].text)
            if _tokens_match(target, heard) or _token_close(target, heard):
                matched.append(words[j])
                wi = j + 1
                found = True
                break
        if not found and wi < len(words):
            matched.append(words[wi])
            wi += 1

    if not matched:
        take = min(len(block_tokens), len(words) - start)
        matched = words[start : start + max(1, take)]
        wi = start + len(matched)
    return matched, wi


def _cue_from_words(
    seg: TtsSegmentResult, matched: list[TtsWord], display: str
) -> tuple[float, float, str] | None:
    if not matched or not display.strip():
        return None
    start = max(0.0, seg.global_start + matched[0].start - _ALIGN_PAD_START)
    end = seg.global_start + matched[-1].end + _ALIGN_PAD_END
    if end - start < _MIN_CUE_SEC:
        end = start + _MIN_CUE_SEC
    return start, end, display


def _events_from_segment(seg: TtsSegmentResult) -> list[tuple[float, float, str]]:
    """音频优先：先按停顿分短语，再按排版分屏，每屏对齐到对应 TTS 词。"""
    if not seg.words:
        return []

    gap = max(0.08, get_settings().tts_pause_gap_sec)
    events: list[tuple[float, float, str]] = []

    for phrase in _group_words_by_pause(seg.words, gap=gap):
        raw = " ".join(w.text for w in phrase)
        formatted = format_subtitle_display(raw)
        blocks = split_display_into_captions(formatted)
        if not blocks:
            continue

        cursor = 0
        for block in blocks:
            matched, cursor = _consume_words_for_block(block, phrase, cursor)
            cue = _cue_from_words(seg, matched, block)
            if cue:
                events.append(cue)

        if cursor < len(phrase):
            tail = phrase[cursor:]
            tail_text = format_subtitle_display(" ".join(w.text for w in tail))
            for block in split_display_into_captions(tail_text):
                matched, cursor = _consume_words_for_block(block, phrase, cursor)
                cue = _cue_from_words(seg, matched, block)
                if cue:
                    events.append(cue)

    return events


def build_tts_caption_events(segments: list[TtsSegmentResult]) -> list[tuple[float, float, str]]:
    events: list[tuple[float, float, str]] = []
    for seg in segments:
        events.extend(_events_from_segment(seg))
    events.sort(key=lambda e: e[0])
    return _smooth_events(events)


def _smooth_events(events: list[tuple[float, float, str]]) -> list[tuple[float, float, str]]:
    if not events:
        return []
    smoothed: list[tuple[float, float, str]] = []
    for start, end, text in sorted(events, key=lambda e: e[0]):
        start = max(0.0, start)
        end = max(end, start + _MIN_CUE_SEC)
        if smoothed and start < smoothed[-1][1]:
            prev_s, prev_e, prev_t = smoothed[-1]
            split = (prev_e + start) / 2
            smoothed[-1] = (prev_s, max(prev_s + _MIN_CUE_SEC, split - 0.03), prev_t)
            start = max(start, smoothed[-1][1] + 0.02)
            end = max(end, start + _MIN_CUE_SEC)
        smoothed.append((start, end, text))
    return smoothed


def _scale_events(
    events: list[tuple[float, float, str]], scale: float
) -> list[tuple[float, float, str]]:
    if abs(scale - 1.0) < 0.01:
        return events
    return [
        (max(0.0, s * scale), max(s * scale + _MIN_CUE_SEC, e * scale), t)
        for s, e, t in events
    ]


def _speech_end_time(segments: list[TtsSegmentResult]) -> float:
    if not segments:
        return 0.0
    return max(seg.global_start + seg.audio_duration for seg in segments) + 0.2


def _fit_master_to_video(
    master_wav: Path,
    events: list[tuple[float, float, str]],
    work_dir: Path,
    *,
    target_sec: float,
) -> tuple[Path, list[tuple[float, float, str]], float, str]:
    """仅略微超出目标时长时微加速；明显超出则保持原速，由片尾延长承接。"""
    settings = get_settings()
    duration = _audio_duration(master_wav)
    if duration <= target_sec + 0.12:
        return master_wav, events, 1.0, ""

    max_speedup = max(1.0, settings.tts_max_speedup)
    needed = duration / target_sec
    if needed > max_speedup:
        return master_wav, events, 1.0, ""

    sped = work_dir / "master_fit.wav"
    tempo_wav(master_wav, sped, tempo=needed)
    scale = (duration / needed) / duration
    note = f" · 整体加速×{needed:.2f}"
    return sped, _scale_events(events, scale), scale, note


async def synthesize_voiceover_segments(
    voiceover_a: list[dict[str, Any]],
    voiceover_b: list[dict[str, Any]],
    *,
    voice_profile: dict[str, Any] | None = None,
    account: dict[str, Any] | None = None,
    account_id: str = "",
    voice: str = "",
    work_dir: Path | None = None,
    brand: BrandProfile | None = None,
) -> list[TtsSegmentResult]:
    lang = (voice_profile or {}).get("language")
    if not lang and account:
        lang = account.get("language")
    voice_name = pick_tts_voice(
        voice_profile,
        account=account,
        account_id=account_id,
        override=voice,
        language=lang,
    )
    voice_candidates = iter_tts_voice_candidates(
        voice_profile,
        account=account,
        account_id=account_id,
        override=voice,
        language=lang,
    )
    if work_dir is None:
        raise ValueError("synthesize_voiceover_segments 需要 work_dir")
    base_dir = work_dir

    track = _collect_tts_items(voiceover_a, voiceover_b)
    raw_segments: list[TtsSegmentResult] = []
    active_voice = ""

    for idx, item in enumerate(track):
        text = _tts_input_text(item, language=lang, brand=brand)
        if not text:
            continue
        display = format_subtitle_display(caption_source_text(item), brand=brand)
        display_blocks = split_display_into_captions(display, brand=brand)
        spoken_words = _spoken_words_for_item(item, brand=brand)
        spoken_chunks = _split_spoken_across_blocks(spoken_words, display_blocks)

        candidates = (
            [active_voice] + [v for v in voice_candidates if v != active_voice]
            if active_voice
            else voice_candidates
        )
        wav, words, duration, voice_used = await _synthesize_segment(
            text, candidates, base_dir, f"seg_{idx:02d}"
        )
        active_voice = voice_used
        raw_segments.append(
            TtsSegmentResult(
                global_start=0.0,
                spoken=text,
                display_blocks=display_blocks,
                spoken_chunks=spoken_chunks,
                words=words,
                wav_path=wav,
                audio_duration=duration,
            )
        )

    settings = get_settings()
    return _schedule_segments_sequential(
        raw_segments,
        gap_sec=max(0.0, settings.tts_segment_gap_sec),
    ), active_voice or voice_name


async def apply_tts_post_production(
    video_path: str | Path,
    voiceover_a: list[dict[str, Any]],
    voiceover_b: list[dict[str, Any]],
    *,
    voice_profile: dict[str, Any] | None = None,
    account: dict[str, Any] | None = None,
    account_id: str = "",
    total_duration: float = 30.0,
    brand: BrandProfile | None = None,
) -> TtsPostResult:
    settings = get_settings()
    video = Path(video_path)
    if not video.is_file():
        raise FileNotFoundError(f"视频不存在: {video}")

    target = settings.tts_fit_to_video_sec or total_duration

    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        segments, voice_used = await synthesize_voiceover_segments(
            voiceover_a,
            voiceover_b,
            voice_profile=voice_profile,
            account=account,
            account_id=account_id,
            work_dir=work,
            brand=brand,
        )
        if not segments:
            raise RuntimeError("无口播台词，无法生成 TTS")

        voice_name = voice_used or pick_tts_voice(
            voice_profile,
            account=account,
            account_id=account_id,
            language=(voice_profile or {}).get("language"),
        )
        delayed = [(seg.global_start, seg.wav_path) for seg in segments if seg.wav_path]
        speech_end = max(target, _speech_end_time(segments))
        master_wav = work / "master.wav"
        mix_delayed_segments(delayed, total_duration=speech_end, out_path=master_wav)

        events = build_tts_caption_events(segments)
        master_wav, events, _scale, fit_note = _fit_master_to_video(
            master_wav, events, work, target_sec=target
        )
        audio_dur = _audio_duration(master_wav)
        _, final_dur = replace_video_audio(video, master_wav)
        extend_note = ""
        if final_dur > target + 0.2:
            extend_note = f" · 片尾延长 {final_dur - target:.1f}s"

        provider = settings.tts_provider or "edge"
        detail = (
            f"Edge TTS · {voice_name} · 自然语速 · {len(segments)} 段 · "
            f"{len(events)} 条字幕 · 口播 {audio_dur:.1f}s{fit_note}{extend_note}"
        )
        return TtsPostResult(
            video_path=video,
            events=events,
            provider=provider,
            voice=voice_name,
            segment_count=len(segments),
            detail=detail,
        )


def apply_tts_post_production_sync(
    video_path: str | Path,
    voiceover_a: list[dict[str, Any]],
    voiceover_b: list[dict[str, Any]],
    *,
    voice_profile: dict[str, Any] | None = None,
    total_duration: float = 30.0,
) -> TtsPostResult:
    return asyncio.run(
        apply_tts_post_production(
            video_path,
            voiceover_a,
            voiceover_b,
            voice_profile=voice_profile,
            total_duration=total_duration,
        )
    )
