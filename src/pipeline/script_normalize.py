"""脚本分镜规范化：限制镜数、剔除插电/插口类画面描述。"""

import re
from typing import Any

MAX_SHOTS = 3

_PLUG_RE = re.compile(
    r"插(?:电|入|上|口|座|头)|插座|插口|插孔|"
    r"plug(?:ging|ged|s)?|outlet|socket|NEMA|"
    r"insert(?:ing|s)?\s+(?:a\s+)?(?:plug|cable|cord)|"
    r"connect(?:ing|s)?\s+(?:to|into)\s+(?:outlet|socket|port|wall)|"
    r"(?:AC|USB|RV|12V|DC)\s+(?:outlet|port|socket)|"
    r"port\s+close[- ]?up|outlet\s+close[- ]?up",
    re.IGNORECASE,
)

_SAFE_VISUAL = (
    "Product unit on lifestyle counter or outdoor table, medium-wide static shot, "
    "whole product in frame with real scene props, ambient natural light, "
    "no port close-up, no plugging cables or inserting plugs"
)


def _scrub_plug_from_visual(visual: str) -> str:
    if not visual or not _PLUG_RE.search(visual):
        return visual
    return _SAFE_VISUAL


def _merge_shot_group(group: list[dict[str, Any]]) -> dict[str, Any]:
    if len(group) == 1:
        return dict(group[0])
    base = dict(group[0])
    times = [s.get("time", "") for s in group]
    start = times[0].split("-")[0].strip() if times[0] else ""
    end = times[-1].split("-")[-1].strip() if times[-1] else ""
    if start and end:
        base["time"] = f"{start}-{end}"
    base["visual"] = " ".join(s.get("visual", "") for s in group if s.get("visual"))
    base["audio"] = " ".join(s.get("audio", "") for s in group if s.get("audio"))
    overlays = [s.get("overlay", "") for s in group if s.get("overlay")]
    if overlays:
        base["overlay"] = " / ".join(overlays)
    return base


def normalize_shots(shots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not shots:
        return []

    cleaned = []
    for shot in shots:
        item = dict(shot)
        item["visual"] = _scrub_plug_from_visual(item.get("visual", ""))
        cleaned.append(item)

    if len(cleaned) <= MAX_SHOTS:
        return cleaned

    first = cleaned[0]
    middle = _merge_shot_group(cleaned[1:-1])
    last = cleaned[-1]
    return [first, middle, last]


def normalize_script_data(data: dict[str, Any]) -> dict[str, Any]:
    out = dict(data)
    shots = out.get("shots")
    if isinstance(shots, list) and shots:
        out["shots"] = normalize_shots(shots)
    return out
