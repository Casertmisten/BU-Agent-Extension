# tests/test_agent.py
import pytest
from unittest.mock import AsyncMock
from agent.agent import BrowserAgent


def _make_config():
    return {
        "llm": {"provider": "dashscope", "model": "qwen-plus", "api_key": "test-key"},
        "vlm": {"provider": "dashscope", "model": "qwen-plus", "api_key": "test-key"},
    }


def test_agent_init():
    """测试 Agent 初始化。"""
    agent = BrowserAgent(_make_config())
    assert agent._agent is None
    agent.init()
    assert agent._agent is not None


def test_agent_init_idempotent():
    """测试 Agent 不会重复创建。"""
    agent = BrowserAgent(_make_config())
    agent.init()
    old = agent._agent
    agent.init()
    assert agent._agent is old


def test_agent_attach_ws():
    """测试 WebSocket 绑定。"""
    agent = BrowserAgent(_make_config())
    mock_ws = AsyncMock()
    agent.attach_ws(mock_ws)
    assert agent._current_ws is mock_ws
    assert agent.conn._ws is mock_ws


def test_agent_reconnect():
    """测试 WebSocket 重连更新引用。"""
    agent = BrowserAgent(_make_config())
    ws1 = AsyncMock()
    ws2 = AsyncMock()
    agent.attach_ws(ws1)
    agent.attach_ws(ws2)
    assert agent._current_ws is ws2
    assert agent.conn._ws is ws2


def test_agent_properties():
    """测试属性访问。"""
    agent = BrowserAgent(_make_config())
    assert agent.conn is not None
    assert agent.viewport_info == {}


@pytest.mark.asyncio
async def test_agent_busy_rejects():
    """测试 Agent 忙碌时拒绝新请求。"""
    agent = BrowserAgent(_make_config())
    agent.init()
    agent._busy = True

    events = []
    async for evt in agent.run("test"):
        events.append(evt)

    assert len(events) == 1
    assert "[BUSY]" in events[0]["content"]
