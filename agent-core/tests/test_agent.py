# tests/test_agent.py
import os
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



# agent-core 目录的绝对路径（__file__ 为 tests/test_agent.py），
# 使技能目录解析不依赖 pytest 的 CWD。生产环境 server.py 在 agent-core/ 下启动，
# config.yaml 里的 "./skills" 相对 agent-core/，与此处一致。
_AGENT_CORE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _make_config():
    return {
        "llm": {"provider": "dashscope", "model": "qwen-plus", "api_key": "test-key"},
        "vlm": {"provider": "dashscope", "model": "qwen-plus", "api_key": "test-key"},
        "skills": {"dirs": [os.path.join(_AGENT_CORE_DIR, "skills")]},
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


def test_reset_context_rebuilds_agent():
    """新建会话：重建 Agent 实例，state 全新（空 context、新 session_id），permission 保留。"""
    from agentscope.message import UserMsg

    agent = BrowserAgent(_make_config())
    agent.init()
    old = agent._agent
    old.state.context.append(UserMsg(name="user", content="旧消息"))
    old.state.summary = "旧摘要"
    old.state.cur_iter = 5
    old_permission = old.state.permission_context

    agent.reset_context()

    new = agent._agent
    assert new is not old                       # 重建为新实例
    assert new.state.context == []              # 全新空 context
    assert new.state.summary == ""
    assert new.state.cur_iter == 0
    assert new.state.session_id != old.state.session_id
    assert new.state.permission_context is old_permission  # permission 保留（同一对象）


def test_reset_context_no_agent_is_noop():
    """未 init 时 reset_context 安全无操作。"""
    agent = BrowserAgent(_make_config())
    agent.reset_context()  # self._agent is None，不应抛错
    assert agent._agent is None


def test_reset_context_isolates_orphan_tool_writes():
    """orphan 工具 task 完成后写旧 Agent.state，不得污染新会话的 Agent.state。

    复现 bug：agentscope 工具在独立 gather_task 中执行，cancel 不级联，orphan
    工具完成后会 _save_to_context 写 state.context。仅清空 state 时 orphan 写
    同一对象会污染；重建 Agent 实例后 orphan 写旧 state，新 state 保持干净。
    """
    from agentscope.message import UserMsg

    agent = BrowserAgent(_make_config())
    agent.init()
    old = agent._agent  # 持有旧 Agent 引用（模拟 orphan 工具 task 的 self 绑定）

    agent.reset_context()
    new = agent._agent
    assert new is not old  # 重建为新实例，而非清空同一对象

    # 模拟 orphan 工具 task 完成后写旧 Agent 的 state（_save_to_context 行为）
    old.state.context.append(UserMsg(name="assistant", content="旧工具结果"))

    # 新会话的 state 不受 orphan 写入影响
    assert new.state.context == []


@pytest.mark.asyncio
async def test_list_skills_returns_example():
    """init 后 list_skills 应返回 [{name, description}]，含 example。"""
    agent = BrowserAgent(_make_config())
    agent.init()
    skills = await agent.list_skills()
    names = [s["name"] for s in skills]
    assert "example" in names
    example = next(s for s in skills if s["name"] == "example")
    assert "description" in example
    assert isinstance(example["description"], str)


@pytest.mark.asyncio
async def test_list_skills_empty_when_no_dirs():
    """skills.dirs 为空时 list_skills 返回空列表，不报错。"""
    config = _make_config()
    config["skills"] = {"dirs": []}
    agent = BrowserAgent(config)
    agent.init()
    skills = await agent.list_skills()
    assert skills == []


def test_run_yields_token_usage():
    """run() 应累加 MODEL_CALL_END 的 token，并在 [DONE] 前 yield token_usage 事件。"""
    import asyncio
    from unittest.mock import MagicMock, patch
    from agentscope.event import EventType

    agent = BrowserAgent(_make_config())
    agent.init()

    # 构造假事件流：2 次 MODEL_CALL_END + 1 段文本 + done 工具
    fake_events = [
        MagicMock(type=EventType.MODEL_CALL_END, input_tokens=5000, output_tokens=200),
        MagicMock(type=EventType.TEXT_BLOCK_DELTA, delta="分析中"),
        MagicMock(type=EventType.MODEL_CALL_END, input_tokens=5200, output_tokens=150),
        MagicMock(type=EventType.TOOL_CALL_START, tool_call_id="t1", tool_call_name="done"),
        MagicMock(type=EventType.TOOL_RESULT_END, tool_call_id="t1", state="success"),
    ]

    async def collect():
        results = []
        with patch.object(agent._agent, "reply_stream",
                          return_value=AsyncIteratorMock(fake_events)):
            async for item in agent.run("测试指令"):
                results.append(item)
        return results

    results = asyncio.run(collect())

    # 找到 token_usage 事件
    token_events = [r for r in results
                    if r.get("type") == "event"
                    and r.get("event", {}).get("type") == "token_usage"]
    assert len(token_events) == 1
    assert token_events[0]["event"]["data"]["input"] == 10200
    assert token_events[0]["event"]["data"]["output"] == 350

    # token_usage 应在 [DONE] 之前
    tu_idx = next(i for i, r in enumerate(results)
                  if r.get("event", {}).get("type") == "token_usage")
    done_idx = next(i for i, r in enumerate(results)
                    if r.get("type") == "stream" and r.get("content") == "[DONE]")
    assert tu_idx < done_idx
