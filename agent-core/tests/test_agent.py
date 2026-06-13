# tests/test_agent.py
import pytest
from unittest.mock import AsyncMock
from agent.agent import BrowserAgent

class AsyncIteratorMock:
    """模拟 async for 迭代器。"""
    def __init__(self, items):
        self._items = iter(items)
    def __aiter__(self):
        return self
    async def __anext__(self):
        try:
            return next(self._items)
        except StopIteration:
            raise StopAsyncIteration



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

@pytest.mark.asyncio
async def test_activity_status_events():
    """测试 activity_status 事件在正确时机推送。"""
    from unittest.mock import MagicMock, patch

    agent = BrowserAgent(_make_config())
    agent.init()

    mock_events = []

    evt_text = MagicMock()
    evt_text.type = "TEXT_BLOCK_DELTA"
    evt_text.delta = "思考中..."
    mock_events.append(evt_text)

    evt_start = MagicMock()
    evt_start.type = "TOOL_CALL_START"
    evt_start.tool_call_id = "tc_1"
    evt_start.tool_call_name = "parse_dom"
    mock_events.append(evt_start)

    evt_delta = MagicMock()
    evt_delta.type = "TOOL_CALL_DELTA"
    evt_delta.tool_call_id = "tc_1"
    evt_delta.delta = "{}"
    mock_events.append(evt_delta)

    evt_result_delta = MagicMock()
    evt_result_delta.type = "TOOL_RESULT_TEXT_DELTA"
    evt_result_delta.tool_call_id = "tc_1"
    evt_result_delta.delta = "ok"
    mock_events.append(evt_result_delta)

    evt_end = MagicMock()
    evt_end.type = "TOOL_RESULT_END"
    evt_end.tool_call_id = "tc_1"
    evt_end.state = "success"
    mock_events.append(evt_end)

    with patch.object(agent._agent, "reply_stream", return_value=AsyncIteratorMock(mock_events)):
        events = []
        async for evt in agent.run("测试指令"):
            events.append(evt)

    status_events = [e for e in events if e.get("type") == "event" and e["event"]["type"] == "activity_status"]
    assert len(status_events) >= 3
    assert status_events[0]["event"]["data"]["status"] == "thinking"
    assert any(e["event"]["data"]["status"] == "executing" for e in status_events)
    assert any(e["event"]["data"]["status"] == "done" for e in status_events)


@pytest.mark.asyncio
async def test_reflection_event_emitted():
    """测试 reflection 事件在 TOOL_CALL_START 前从文本中解析并推送。"""
    from unittest.mock import MagicMock, patch

    agent = BrowserAgent(_make_config())
    agent.init()

    mock_events = []

    reflection_text = '{"evaluation_previous_goal": "成功导航", "memory": "用户要搜索xxx", "next_goal": "输入关键词"}'
    evt_text = MagicMock()
    evt_text.type = "TEXT_BLOCK_DELTA"
    evt_text.delta = reflection_text
    mock_events.append(evt_text)

    for evt_type, tid, extra in [
        ("TOOL_CALL_START", "tc_1", {"tool_call_name": "input_text"}),
        ("TOOL_CALL_DELTA", "tc_1", {"delta": '{"target_id": "5", "text": "test"}'}),
        ("TOOL_RESULT_TEXT_DELTA", "tc_1", {"delta": "ok"}),
        ("TOOL_RESULT_END", "tc_1", {"state": "success"}),
    ]:
        evt = MagicMock()
        evt.type = evt_type
        evt.tool_call_id = tid
        for k, v in extra.items():
            setattr(evt, k, v)
        mock_events.append(evt)

    with patch.object(agent._agent, "reply_stream", return_value=AsyncIteratorMock(mock_events)):
        events = []
        async for evt in agent.run("测试"):
            events.append(evt)

    reflections = [e for e in events if e.get("type") == "event" and e["event"]["type"] == "reflection"]
    assert len(reflections) == 1
    assert reflections[0]["event"]["data"]["evaluation_previous_goal"] == "成功导航"
    assert reflections[0]["event"]["data"]["memory"] == "用户要搜索xxx"
    assert reflections[0]["event"]["data"]["next_goal"] == "输入关键词"


@pytest.mark.asyncio
async def test_parse_reflection():
    """测试 _parse_reflection 辅助方法。"""
    agent = BrowserAgent(_make_config())

    text = '一些文本 {"evaluation_previous_goal": "成功", "memory": "记忆", "next_goal": "目标"} 更多文本'
    result = agent._parse_reflection(text)
    assert result is not None
    assert result["evaluation_previous_goal"] == "成功"
    assert result["memory"] == "记忆"
    assert result["next_goal"] == "目标"

    assert agent._parse_reflection("无 JSON 文本") is None
    assert agent._parse_reflection("") is None


def test_reset_context_clears_state():
    """新建会话：清历史、换 session_id、换新 tool/tasks context，保留 permission。"""
    from types import SimpleNamespace
    from agentscope.state import AgentState
    from agentscope.message import UserMsg

    agent = BrowserAgent(_make_config())
    # 不调 init()，直接注入一个带真实 AgentState 的 _agent，聚焦 reset_context 本身
    agent._agent = SimpleNamespace(state=AgentState())
    st = agent._agent.state
    st.context.append(UserMsg(name="user", content="旧消息"))
    st.summary = "旧摘要"
    st.cur_iter = 5
    st.tool_context.activated_groups.append("group_a")
    old_sid = st.session_id

    agent.reset_context()

    assert st.context == []
    assert st.summary == ""
    assert st.cur_iter == 0
    assert st.session_id != old_sid
    assert st.tool_context.activated_groups == []
    # permission_context 保留（用户级授权跨会话有效）
    assert st.permission_context is not None


def test_reset_context_no_agent_is_noop():
    """未 init 时 reset_context 安全无操作。"""
    agent = BrowserAgent(_make_config())
    agent.reset_context()  # self._agent is None，不应抛错
    assert agent._agent is None
