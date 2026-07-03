"""Hermes Skill 远程安装清单 — 与 Creative Agent /.well-known/skills 同协议。"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from src.config import ROOT

SKILLS_ROOT = ROOT / "mcp_server" / "hermes_skills"
PACKAGE_NAME = "vidau-adflow-skills"
PACKAGE_VERSION = "0.2.0"


def _parse_description(block: str) -> str:
    m = re.search(
        r"^description:\s*>-\s*\n((?:[ \t]+.+\n?)+)",
        block,
        re.MULTILINE,
    )
    if m:
        return " ".join(line.strip() for line in m.group(1).splitlines() if line.strip())
    m = re.search(r'^description:\s*["\']?(.+?)["\']?\s*$', block, re.MULTILINE)
    return m.group(1).strip() if m else ""


def _skill_meta(skill_dir: Path) -> dict[str, Any] | None:
    md_path = skill_dir / "SKILL.md"
    if not md_path.is_file():
        return None
    text = md_path.read_text(encoding="utf-8")
    name = skill_dir.name
    description = ""
    fm = re.match(r"^---\s*\n(.*?)\n---", text, re.DOTALL)
    if fm:
        block = fm.group(1)
        nm = re.search(r"^name:\s*(\S+)", block, re.MULTILINE)
        if nm:
            name = nm.group(1).strip()
        description = _parse_description(block)
    return {
        "name": name,
        "description": description or f"AdFlow skill: {name}",
        "files": ["SKILL.md"],
    }


@lru_cache(maxsize=1)
def build_skills_index() -> dict[str, Any]:
    skills: list[dict[str, Any]] = []
    if SKILLS_ROOT.is_dir():
        for child in sorted(SKILLS_ROOT.iterdir()):
            if not child.is_dir():
                continue
            meta = _skill_meta(child)
            if meta:
                skills.append(meta)
    return {
        "package": PACKAGE_NAME,
        "version": PACKAGE_VERSION,
        "description": "VidAU AdFlow — Hermes Skill 包（Blueprint 产线 / UGC 台词 / 画布）",
        "skills": skills,
    }


def skill_md_path(skill_name: str) -> Path | None:
    direct = SKILLS_ROOT / skill_name / "SKILL.md"
    if direct.is_file():
        return direct
    if SKILLS_ROOT.is_dir():
        for child in SKILLS_ROOT.iterdir():
            if not child.is_dir():
                continue
            md = child / "SKILL.md"
            if not md.is_file():
                continue
            text = md.read_text(encoding="utf-8")
            fm = re.match(r"^---\s*\n(.*?)\n---", text, re.DOTALL)
            if fm:
                nm = re.search(r"^name:\s*(\S+)", fm.group(1), re.MULTILINE)
                if nm and nm.group(1).strip() == skill_name:
                    return md
    return None
