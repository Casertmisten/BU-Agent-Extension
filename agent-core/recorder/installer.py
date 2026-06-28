# recorder/installer.py
"""安装器：把蒸馏结果写入 skills 目录，注入 frontmatter。

写入 agent-core/skills/<name>/SKILL.md（已有 LocalSkillLoader 覆盖该目录，
利用其实时扫描机制立即生效）。同时留档原始 trace 供重蒸馏。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .types import DistillResult

# 只允许 kebab-case 字符
_VALID_NAME_RE = re.compile(r"[^a-z0-9]+")


def sanitize_skill_name(raw: str) -> str:
    """把任意字符串转成合法的 kebab-case 技能名。

    中文等非 ASCII 字符会被移除（保持简单，不做拼音转换）；
    为空时回退到 recorded-skill。
    """
    s = raw.lower().strip()
    s = _VALID_NAME_RE.sub("-", s)
    s = re.sub(r"-{2,}", "-", s).strip("-")
    s = s[:64].strip("-")
    return s if s else "recorded-skill"


def _unique_dir(base: Path, name: str) -> Path:
    """若目录已存在，追加 -2/-3 后缀直到不冲突。"""
    candidate = base / name
    if not candidate.exists():
        return candidate
    i = 2
    while True:
        c = base / f"{name}-{i}"
        if not c.exists():
            return c
        i += 1


def _frontmatter(name: str, description: str) -> str:
    desc = re.sub(r"[`*_#>]", "", description or name).strip()
    desc = re.sub(r"\s+", " ", desc)[:1024] or name
    return f"---\nname: {name}\ndescription: {desc}\n---\n\n"


def install_skill(
    result: DistillResult,
    skills_root: Path,
    trace_events: list[dict[str, Any]] | None = None,
    trace_id: str = "",
) -> dict[str, str]:
    """写入 SKILL.md + 原始 trace 留档。

    Args:
        result: 蒸馏结果。
        skills_root: skills 根目录（如 agent-core/skills）。
        trace_events: 原始事件列表（留档供重蒸馏）。
        trace_id: 轨迹 ID。

    Returns:
        {"skill_name": 实际写入的名, "skill_path": SKILL.md 路径}
    """
    skill_name = sanitize_skill_name(result.skill_name)
    skill_dir = _unique_dir(skills_root, skill_name)
    skill_dir.mkdir(parents=True, exist_ok=True)

    body = result.skill_md.strip()
    # 若模型已输出 frontmatter 则不重复注入
    if re.match(r"^\s*---\s*\n", body):
        content = body + "\n"
    else:
        content = _frontmatter(skill_name, result.description) + body + "\n"

    skill_path = skill_dir / "SKILL.md"
    skill_path.write_text(content, encoding="utf-8")

    # 原始 trace 留档（_ 前缀避免被 LocalSkillLoader 误读，它只认 SKILL.md）
    if trace_events is not None:
        trace_path = skill_dir / "_source_trace.json"
        trace_path.write_text(
            json.dumps({"trace_id": trace_id, "events": trace_events}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    return {"skill_name": skill_dir.name, "skill_path": str(skill_path)}
