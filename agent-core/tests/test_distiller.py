# tests/test_distiller.py
"""distiller 单测：prompt 构建、JSON 解析、错误降级。"""
import pytest
from unittest.mock import AsyncMock, MagicMock

from recorder.distiller import (
    build_distill_prompt, parse_skill_json, distill_segments,
)
from recorder.types import Segment, NormalizedEvent
from agentscope.message import TextBlock


def _seg(domain="example.com", events=None, summary="click 登录"):
    return Segment(
        segment_id="t1::0::3",
        source_track_id="t1",
        domain=domain,
        start_idx=0,
        end_idx=3,
        events=events or [],
        boundary_reason="end_of_track",
        entry_url="https://example.com",
        exit_url="https://example.com/done",
        duration_ms=3000,
        event_summary=summary,
    )


def test_build_prompt_contains_label_and_events():
    prompt = build_distill_prompt([_seg()], label="登录测试网站")
    assert "登录测试网站" in prompt
    assert "click 登录" in prompt
    assert "example.com" in prompt
    assert "skill_md" in prompt
    assert "kebab-case" in prompt


def test_build_prompt_multi_segment():
    segs = [
        _seg(domain="a.com", summary="click A"),
        _seg(domain="b.com", summary="click B"),
    ]
    prompt = build_distill_prompt(segs)
    assert "click A" in prompt
    assert "click B" in prompt


def test_parse_skill_json_clean():
    data = parse_skill_json('{"skill_name": "login", "description": "登录", "skill_md": "# x"}')
    assert data["skill_name"] == "login"
    assert data["skill_md"] == "# x"


def test_parse_skill_json_with_code_fence():
    raw = '```json\n{"skill_name": "a", "description": "b", "skill_md": "c"}\n```'
    data = parse_skill_json(raw)
    assert data["skill_name"] == "a"


def test_parse_skill_json_extracts_object_from_text():
    raw = '这是结果：\n{"skill_name": "x", "description": "y", "skill_md": "z"}\n谢谢'
    data = parse_skill_json(raw)
    assert data["skill_name"] == "x"


def test_parse_skill_json_invalid_raises():
    with pytest.raises(ValueError):
        parse_skill_json("不是 JSON")


@pytest.mark.asyncio
async def test_distill_segments_calls_model_and_parses():
    """distill_segments 调 model（async def 返回 ChatResponse），解析返回的 JSON 为 DistillResult。"""
    from agentscope.model._model_response import ChatResponse

    async def _fake_model(_msgs):
        return ChatResponse(
            content=[TextBlock(type="text", text='{"skill_name": "login-flow", "description": "登录网站", "skill_md": "# 登录流程"}')],
            is_last=True,
        )

    mock_model = MagicMock(side_effect=_fake_model)
    result = await distill_segments([_seg()], mock_model, label="登录")
    assert result.skill_name == "login-flow"
    assert result.description == "登录网站"
    assert "# 登录流程" in result.skill_md
