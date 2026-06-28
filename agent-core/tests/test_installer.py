# tests/test_installer.py
"""installer 单测：命名、frontmatter、冲突处理、trace 留档。"""
import json
from pathlib import Path

import pytest

from recorder.installer import sanitize_skill_name, install_skill
from recorder.types import DistillResult


def test_sanitize_kebab():
    assert sanitize_skill_name("Login Flow!") == "login-flow"
    # 含路径分隔符应被替换
    assert "/" not in sanitize_skill_name("a/b")
    assert ".." not in sanitize_skill_name("a..b")


def test_sanitize_chinese_falls_back():
    """纯中文 sanitize 后为空 → fallback recorded-skill。"""
    assert sanitize_skill_name("搜索并加入购物车") == "recorded-skill"


def test_sanitize_empty_fallback():
    assert sanitize_skill_name("") == "recorded-skill"
    assert sanitize_skill_name("---") == "recorded-skill"


def test_install_skill_writes_file(tmp_path: Path):
    result = DistillResult(
        skill_name="login-flow",
        description="登录网站",
        skill_md="# 登录\n\n1. 点击登录",
    )
    skills_dir = tmp_path / "skills"
    trace_events = [{"kind": "action", "action_type": "click", "url": "https://x.com", "timestamp": 0}]

    installed = install_skill(result, skills_dir, trace_events=trace_events, trace_id="t1")

    skill_file = skills_dir / "login-flow" / "SKILL.md"
    assert skill_file.exists()
    content = skill_file.read_text()
    assert content.startswith("---\n")
    assert "name: login-flow" in content
    assert "description: 登录网站" in content
    assert "# 登录" in content


def test_install_skill_keeps_source_trace(tmp_path: Path):
    result = DistillResult(skill_name="x", description="y", skill_md="z")
    skills_dir = tmp_path / "skills"
    trace_events = [{"kind": "action", "timestamp": 1}]

    install_skill(result, skills_dir, trace_events=trace_events, trace_id="t1")

    trace_file = skills_dir / "x" / "_source_trace.json"
    assert trace_file.exists()
    data = json.loads(trace_file.read_text())
    assert data["trace_id"] == "t1"


def test_install_skill_name_conflict_suffix(tmp_path: Path):
    """目录已存在时追加 -2 后缀。"""
    result = DistillResult(skill_name="login", description="d", skill_md="m")
    skills_dir = tmp_path / "skills"
    install_skill(result, skills_dir, trace_events=[], trace_id="t1")
    # 第二次同名
    installed2 = install_skill(result, skills_dir, trace_events=[], trace_id="t2")
    assert installed2["skill_name"] == "login-2"
    assert (skills_dir / "login-2" / "SKILL.md").exists()
