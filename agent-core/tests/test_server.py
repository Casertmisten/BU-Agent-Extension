# tests/test_server.py
import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock
from browser.connection import BrowserConnection


def test_import_server():
    from server import handle_client, _get_or_create_agent
    assert callable(handle_client)
    assert callable(_get_or_create_agent)


def test_get_or_create_agent():
    """测试 Agent 单例创建。"""
    import server
    server._agent = None

    from server import _get_or_create_agent
    config = {
        "llm": {"provider": "dashscope", "model": "qwen-plus", "api_key": "test-key"},
        "vlm": {"provider": "dashscope", "model": "qwen-plus", "api_key": "test-key"},
    }
    agent = _get_or_create_agent(config)
    assert agent is not None

    # 二次调用返回同一个实例
    agent2 = _get_or_create_agent(config)
    assert agent is agent2

    # 清理
    server._agent = None


class FakeWS:
    """模拟 WebSocket：按顺序返回消息，记录 send 的内容。"""

    def __init__(self, messages):
        self._messages = iter(messages)
        self.sent = []

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self._messages)
        except StopIteration:
            raise StopAsyncIteration

    async def send(self, data):
        self.sent.append(data)


def _mock_agent():
    """构造一个 mock BrowserAgent，reset_context 可追踪。"""
    agent = MagicMock()
    agent._busy = False
    agent._current_ws = None
    agent.conn = BrowserConnection()
    return agent


@pytest.mark.asyncio
async def test_new_session_resets_context_when_idle():
    """空闲时收到 new_session，调用 reset_context，不发 done 事件。"""
    import server
    agent = _mock_agent()
    server._agent = agent
    server._current_task = None

    try:
        ws = FakeWS([json.dumps({"type": "new_session"})])
        await server.handle_client(ws, {})

        agent.reset_context.assert_called_once()
        # 空闲（无运行任务）不应发 done 事件
        assert not any('"activity_status"' in s and '"done"' in s for s in ws.sent)
    finally:
        server._agent = None
        server._current_task = None


@pytest.mark.asyncio
async def test_new_session_cancels_running_task_then_resets():
    """有运行中任务时 new_session：取消并 await 旧任务，发 done 事件，再 reset。"""
    import server

    async def _hang():
        await asyncio.Future()  # 永不自然完成，只能被 cancel

    task = asyncio.create_task(_hang())
    await asyncio.sleep(0)  # 让 task 启动

    agent = _mock_agent()
    server._agent = agent
    server._current_task = task

    try:
        ws = FakeWS([json.dumps({"type": "new_session"})])
        await server.handle_client(ws, {})

        assert task.done()  # 旧任务已结束
        agent.reset_context.assert_called_once()
        assert server._current_task is None
        # 发了 done 事件关闭前端遮罩
        assert any('"activity_status"' in s and '"done"' in s for s in ws.sent)
    finally:
        server._agent = None
        server._current_task = None
