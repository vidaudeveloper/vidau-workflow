"""口播字数预算 — 按成片时长/分段策略适配 TTS 自然语速。"""

from __future__ import annotations

import re
from typing import Any

from src.pipeline.workflow_language import is_spanish

# 英语 dual 30s：自然 TTS 约 2.3–2.6 词/秒 → 25–28s ≈ 55–72 词
EN_DUAL_TOTAL_WORDS_MIN = 55
EN_DUAL_TOTAL_WORDS_MAX = 72
EN_PART_A_WORDS_MAX = 36
EN_PART_B_WORDS_MAX = 36
EN_ESTIMATED_WPS = 2.45

# 英语 single ≤15s：约 12–15s ≈ 38–52 词
EN_SINGLE_TOTAL_WORDS_MIN = 38
EN_SINGLE_TOTAL_WORDS_MAX = 52

# 西语 dual 30s：词略长，约 2.1–2.4 词/秒 → 25–28s ≈ 58–75 词
ES_DUAL_TOTAL_WORDS_MIN = 58
ES_DUAL_TOTAL_WORDS_MAX = 75
ES_PART_A_WORDS_MAX = 38
ES_PART_B_WORDS_MAX = 38
ES_ESTIMATED_WPS = 2.25

# 西语 single ≤15s
ES_SINGLE_TOTAL_WORDS_MIN = 42
ES_SINGLE_TOTAL_WORDS_MAX = 58


def _is_single_short(duration_sec: int, segment_strategy: str) -> bool:
    return segment_strategy == "single" and duration_sec <= 15


def _limits(
    language: str | None = None,
    *,
    duration_sec: int = 30,
    segment_strategy: str = "dual",
) -> dict[str, int | float | str]:
    single = _is_single_short(duration_sec, segment_strategy)
    if is_spanish(language):
        if single:
            return {
                "total_min": ES_SINGLE_TOTAL_WORDS_MIN,
                "total_max": ES_SINGLE_TOTAL_WORDS_MAX,
                "part_a_max": ES_SINGLE_TOTAL_WORDS_MAX,
                "part_b_max": 0,
                "wps": ES_ESTIMATED_WPS,
                "target_tts": "12–15",
            }
        return {
            "total_min": ES_DUAL_TOTAL_WORDS_MIN,
            "total_max": ES_DUAL_TOTAL_WORDS_MAX,
            "part_a_max": ES_PART_A_WORDS_MAX,
            "part_b_max": ES_PART_B_WORDS_MAX,
            "wps": ES_ESTIMATED_WPS,
            "target_tts": "25–28",
        }
    if single:
        return {
            "total_min": EN_SINGLE_TOTAL_WORDS_MIN,
            "total_max": EN_SINGLE_TOTAL_WORDS_MAX,
            "part_a_max": EN_SINGLE_TOTAL_WORDS_MAX,
            "part_b_max": 0,
            "wps": EN_ESTIMATED_WPS,
            "target_tts": "12–15",
        }
    return {
        "total_min": EN_DUAL_TOTAL_WORDS_MIN,
        "total_max": EN_DUAL_TOTAL_WORDS_MAX,
        "part_a_max": EN_PART_A_WORDS_MAX,
        "part_b_max": EN_PART_B_WORDS_MAX,
        "wps": EN_ESTIMATED_WPS,
        "target_tts": "25–28",
    }


def _word_count(text: str, language: str | None = None) -> int:
    if is_spanish(language):
        return len(re.findall(r"[\wÀ-ÿ]+", text or "", flags=re.UNICODE))
    return len(re.findall(r"[A-Za-z0-9']+", text or ""))


def count_voiceover_words(items: list[dict[str, Any]], *, language: str | None = None) -> int:
    total = 0
    for item in items:
        spoken = str(item.get("spoken") or item.get("voiceover") or item.get("display") or "")
        total += _word_count(spoken, language)
    return total


def count_script_audio_words(shots: list[dict[str, Any]], *, language: str | None = None) -> int:
    total = 0
    for shot in shots:
        total += _word_count(str(shot.get("audio") or ""), language)
    return total


def estimate_tts_seconds(word_count: int, *, language: str | None = None) -> float:
    if word_count <= 0:
        return 0.0
    return word_count / float(_limits(language)["wps"])


def voiceover_budget_hint(
    language: str | None = None,
    *,
    duration_sec: int = 30,
    segment_strategy: str = "dual",
) -> dict[str, Any]:
    lim = _limits(language, duration_sec=duration_sec, segment_strategy=segment_strategy)
    unit = "西语词" if is_spanish(language) else "英文词"
    single = _is_single_short(duration_sec, segment_strategy)
    if single:
        rules = [
            f"全片口播{unit}数控制在 {lim['total_min']}–{lim['total_max']}（自然 TTS 约 {lim['target_tts']} 秒）",
            "单段 15s 直出：仅 ONE shot，时间轴 0–15s，禁止 Part A / Part B",
            "最多 2–3 个卖点，口播简练",
            "每条 spoken 仅一句短口语",
            "CTA 在 12–15s 内完成",
        ]
    else:
        rules = [
            f"全片口播{unit}数控制在 {lim['total_min']}–{lim['total_max']}（自然 TTS 约 {lim['target_tts']} 秒）",
            f"Part A ≤{lim['part_a_max']} 词，Part B ≤{lim['part_b_max']} 词",
            "每条 spoken 仅一句短口语，time 窗 2–3.5 秒",
            "Part B 必须覆盖 15–18s、18–24s、24–27s、27–30s",
            "CTA（27–30s）合并为 1–2 条短句",
        ]
    return {
        "language": "西语" if is_spanish(language) else "英语",
        "duration_sec": duration_sec,
        "segment_strategy": segment_strategy,
        "target_total_words": f"{lim['total_min']}–{lim['total_max']}",
        "target_tts_duration_sec": lim["target_tts"],
        "part_a_words_max": lim["part_a_max"],
        "part_b_words_max": lim["part_b_max"],
        "rules": rules,
    }


def budget_hint_text(
    language: str | None = None,
    *,
    duration_sec: int = 30,
    segment_strategy: str = "dual",
) -> str:
    hint = voiceover_budget_hint(
        language, duration_sec=duration_sec, segment_strategy=segment_strategy
    )
    lim = _limits(language, duration_sec=duration_sec, segment_strategy=segment_strategy)
    unit = "西语词" if is_spanish(language) else "英文词"
    single = _is_single_short(duration_sec, segment_strategy)
    lines = [
        f"【口播时长预算·{hint['language']}·{duration_sec}s {segment_strategy}】"
        f"全片 {hint['target_total_words']} {unit}"
        f"（TTS 自然语速约 {hint['target_tts_duration_sec']}s）",
    ]
    if single:
        lines.append("单段 0–15s，禁止 Part A/B 双段结构")
    else:
        lines.append(f"Part A ≤{lim['part_a_max']} 词，Part B ≤{lim['part_b_max']} 词")
    lines.extend(f"- {rule}" for rule in hint["rules"])
    return "\n".join(lines)


def check_voiceover_budget(
    voiceover_a: list[dict[str, Any]],
    voiceover_b: list[dict[str, Any]],
    *,
    language: str | None = None,
    duration_sec: int = 30,
    segment_strategy: str = "dual",
) -> dict[str, Any]:
    lim = _limits(language, duration_sec=duration_sec, segment_strategy=segment_strategy)
    total_min = int(lim["total_min"])
    total_max = int(lim["total_max"])
    part_a_max = int(lim["part_a_max"])
    part_b_max = int(lim["part_b_max"])
    single = _is_single_short(duration_sec, segment_strategy)

    words_a = count_voiceover_words(voiceover_a, language=language)
    words_b = count_voiceover_words(voiceover_b, language=language)
    total = words_a + words_b
    est_sec = estimate_tts_seconds(total, language=language)
    warnings: list[str] = []

    if total > total_max:
        warnings.append(
            f"口播共 {total} 词，超出预算 {total_max} 词（预计 TTS {est_sec:.0f}s，易片尾定格或截断）"
        )
    elif total < total_min:
        warnings.append(f"口播仅 {total} 词，偏短（预计 {est_sec:.0f}s）")

    if single:
        if voiceover_b:
            warnings.append("15s 单段不应有 Part B 口播表")
        if words_a > part_a_max:
            warnings.append(f"口播 {words_a} 词，建议 ≤{part_a_max}")
    else:
        if words_a > part_a_max:
            warnings.append(f"Part A 口播 {words_a} 词，建议 ≤{part_a_max}")
        if words_b > part_b_max:
            warnings.append(f"Part B 口播 {words_b} 词，建议 ≤{part_b_max}")

        times_b = []
        for item in voiceover_b:
            raw = str(item.get("time", ""))
            m = re.match(r"(\d+(?:\.\d+)?)", raw.replace(" ", ""))
            if m:
                times_b.append(float(m.group(1)))
        if voiceover_b and (not times_b or min(times_b) > 18.5):
            warnings.append("Part B 缺少 15–18s 承接句")
        if voiceover_b and max(times_b or [0]) < 26:
            warnings.append("Part B 缺少 27–30s CTA 时间窗")

    within = total_min <= total <= total_max
    if single:
        within = within and words_a <= part_a_max and not voiceover_b
    else:
        within = (
            within
            and words_a <= part_a_max
            and words_b <= part_b_max
        )

    return {
        "words_part_a": words_a,
        "words_part_b": words_b,
        "total_words": total,
        "estimated_tts_sec": round(est_sec, 1),
        "within_budget": within,
        "warnings": warnings,
    }


def annotate_voiceover_spec(
    spec: dict[str, Any],
    *,
    language: str | None = None,
    duration_sec: int = 30,
    segment_strategy: str = "dual",
) -> dict[str, Any]:
    vo_a = spec.get("voiceover_part_a") or []
    vo_b = spec.get("voiceover_part_b") or []
    spec = dict(spec)
    lang = language or spec.get("language")
    dur = int(spec.get("duration_sec") or duration_sec)
    strat = str(spec.get("segment_strategy") or segment_strategy)
    spec["voiceover_budget"] = check_voiceover_budget(
        vo_a, vo_b, language=lang, duration_sec=dur, segment_strategy=strat
    )
    return spec
