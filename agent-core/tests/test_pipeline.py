# tests/test_pipeline.py
"""pipeline 单测：端到端编排 + 进度回调。"""
import pytest
from unittest.mock import MagicMock
from pathlib import Path

from recorder.pipeline import run_distill_pipeline
from agentscope.message import TextBlock
from agentscope.model._model_response import ChatResponse


@pytest.mark.asyncio
async def test_pipeline_progress_callbacks(tmp_path: Path):
    """pipeline 应依次回调 atomize/distill/install 三个阶段。"""
    raw_events = [
        {"kind": "action", "action_type": "click", "url": "https://example.com",
         "timestamp": 0, "target": {"tag": "button", "text": "登录", "xpath": "/btn"}},
        {"kind": "action", "action_type": "input", "url": "https://example.com",
         "timestamp": 100, "target": {"tag": "input", "text": "邮箱"},
         "value": {"value": "a@b.com"}},
        {"kind": "action", "action_type": "click", "url": "https://example.com",
         "timestamp": 200, "target": {"tag": "button", "text": "提交", "xpath": "/submit"}},
    ]

    def _fake_model(_msgs):
        async def _gen():
            yield ChatResponse(
                content=[TextBlock(
                    type="text",
                    text='{"skill_name": "login", "description": "登录", "skill_md": "# 登录"}',
                )],
                is_last=True,
            )
        return _gen()

    mock_model = MagicMock(side_effect=_fake_model)
    stages: list[str] = []

    async def on_progress(stage, message):
        stages.append(stage)

    result = await run_distill_pipeline(
        trace_id="t1",
        raw_events=raw_events,
        label="登录测试",
        model=mock_model,
        skills_root=tmp_path / "skills",
        on_progress=on_progress,
    )

    assert "atomize" in stages
    assert "distill" in stages
    assert "install" in stages
    assert result["skill_name"] == "login"
    assert (tmp_path / "skills" / "login" / "SKILL.md").exists()


@pytest.mark.asyncio
async def test_pipeline_empty_events_raises(tmp_path: Path):
    """全是噪音/空事件时应在 atomize 阶段报错。"""
    mock_model = MagicMock()
    with pytest.raises(ValueError, match="未捕获到有效操作"):
        await run_distill_pipeline(
            trace_id="t1",
            raw_events=[],
            label="",
            model=mock_model,
            skills_root=tmp_path / "skills",
        )
