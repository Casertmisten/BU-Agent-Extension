# tests/test_tools.py
"""浏览器工具集（ToolBase 子类）单测。

create_browser_tools() 现返回 list[ToolBase]，工具通过 await tool(**kwargs)
调用，结果为 ToolChunk（文本在 content[0].text）。
"""
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from browser.connection import BrowserConnection
from browser.tools import create_browser_tools


def _by_name(tools, name):
    """按 name 从工具列表中取出实例。"""
    for t in tools:
        if t.name == name:
            return t
    raise KeyError(f"工具不存在: {name}")


def _output_text(chunk) -> str:
    """从 ToolChunk 中提取拼接后的文本。"""
    return "".join(
        b.text for b in chunk.content if getattr(b, "text", None) is not None
    )


@pytest.fixture
def conn():
    c = BrowserConnection()
    c.set_ws(AsyncMock())
    return c


@pytest.mark.asyncio
async def test_parse_page_ax_strategy(conn):
    """ax 策略（默认）发 parse_page action，返回 AX 树。"""
    conn.send_action = AsyncMock(return_value={
        "type": "result", "task_id": "t1", "status": "success",
        "data": {"tree": {"role": "WebArea", "name": "x", "children": [
            {"role": "button", "name": "登录", "id": "agent-00"}]}},
    })
    tool = _by_name(
        create_browser_tools(conn, vlm_model=None, viewport_info={}, dom_strategy="ax"),
        "parse_page",
    )
    result = await tool()
    sent = conn.send_action.call_args[0][0]
    assert sent["action"] == "parse_page"
    assert "WebArea" in _output_text(result)
    assert "agent-00" in _output_text(result)


@pytest.mark.asyncio
async def test_parse_page_flat_strategy(conn):
    """flat 策略发 parse_dom action（旧版扁平列表）。"""
    conn.send_action = AsyncMock(return_value={
        "type": "result", "task_id": "t1", "status": "success",
        "data": {"elements": [{"id": "agent-00", "tag": "button", "text": "Submit"}]},
    })
    tool = _by_name(
        create_browser_tools(conn, vlm_model=None, viewport_info={}, dom_strategy="flat"),
        "parse_page",
    )
    result = await tool()
    sent = conn.send_action.call_args[0][0]
    assert sent["action"] == "parse_dom"
    assert "agent-00" in _output_text(result)


@pytest.mark.asyncio
async def test_parse_page_default_strategy_is_ax(conn):
    """不传 dom_strategy 时默认 ax。"""
    conn.send_action = AsyncMock(return_value={
        "type": "result", "task_id": "t1", "status": "success",
        "data": {"tree": {"role": "WebArea", "name": "", "children": []}},
    })
    tool = _by_name(
        create_browser_tools(conn, vlm_model=None, viewport_info={}),
        "parse_page",
    )
    await tool()
    sent = conn.send_action.call_args[0][0]
    assert sent["action"] == "parse_page"


@pytest.mark.asyncio
async def test_get_element_info(conn):
    conn.send_action = AsyncMock(return_value={
        "type": "result", "task_id": "t1", "status": "success",
        "data": {"tag": "input", "type": "text", "visible": True},
    })
    tool = _by_name(create_browser_tools(conn, vlm_model=None, viewport_info={}), "get_element_info")
    result = await tool(target_id="agent-05")
    assert "input" in _output_text(result)


@pytest.mark.asyncio
async def test_click_element(conn):
    conn.send_action = AsyncMock(return_value={
        "type": "result", "task_id": "t1", "status": "success", "data": {},
    })
    tool = _by_name(create_browser_tools(conn, vlm_model=None, viewport_info={}), "click_element")
    result = await tool(target_id="agent-05")
    assert "success" in _output_text(result).lower()


@pytest.mark.asyncio
async def test_input_text(conn):
    conn.send_action = AsyncMock(return_value={
        "type": "result", "task_id": "t1", "status": "success", "data": {},
    })
    tool = _by_name(create_browser_tools(conn, vlm_model=None, viewport_info={}), "input_text")
    result = await tool(target_id="agent-12", text="hello world")
    assert "success" in _output_text(result).lower()


@pytest.mark.asyncio
async def test_scroll_page(conn):
    conn.send_action = AsyncMock(return_value={
        "type": "result", "task_id": "t1", "status": "success", "data": {},
    })
    tool = _by_name(create_browser_tools(conn, vlm_model=None, viewport_info={}), "scroll_page")
    result = await tool(direction="down", pixels=300)
    assert "success" in _output_text(result).lower()


@pytest.mark.asyncio
async def test_navigate(conn):
    conn.send_action = AsyncMock(return_value={
        "type": "result", "task_id": "t1", "status": "success", "data": {},
    })
    tool = _by_name(create_browser_tools(conn, vlm_model=None, viewport_info={}), "navigate")
    result = await tool(url="https://example.com")
    assert "success" in _output_text(result).lower()


@pytest.mark.asyncio
async def test_wait(conn):
    conn.send_action = AsyncMock(return_value={
        "type": "result", "task_id": "t1", "status": "success", "data": {},
    })
    tool = _by_name(create_browser_tools(conn, vlm_model=None, viewport_info={}), "wait")
    result = await tool(seconds=2)
    assert "success" in _output_text(result).lower()


@pytest.mark.asyncio
async def test_screenshot_analyze(conn):
    # 真实调用路径：await vlm([msg]) -> async generator of chunks，每个 chunk.content 是 list[TextBlock]
    from agentscope.message import TextBlock

    async def _fake_vlm(_msgs):
        async def _gen():
            yield MagicMock(content=[TextBlock(type="text", text="Page shows a login form with email and password fields.")])
        return _gen()

    mock_vlm = MagicMock(side_effect=_fake_vlm)
    conn.send_action = AsyncMock(return_value={
        "type": "result", "task_id": "t1", "status": "success",
        "data": {"image": "iVBORw0KGgoAAAANSUhEUg=="},
    })
    tool = _by_name(create_browser_tools(conn, vlm_model=mock_vlm, viewport_info={}), "screenshot_analyze")
    result = await tool()
    assert "login form" in _output_text(result).lower()


@pytest.mark.asyncio
async def test_cdp_click_coordinate_conversion(conn):
    conn.send_action = AsyncMock(return_value={
        "type": "result", "task_id": "t1", "status": "success", "data": {},
    })
    # DPR 2.0: image pixels 640 -> CSS pixels 320
    tool = _by_name(create_browser_tools(conn, vlm_model=None, viewport_info={"dpr": 2.0}), "cdp_click")
    await tool(x=640.0, y=480.0)

    call_args = conn.send_action.call_args[0][0]
    assert call_args["x"] == 320.0
    assert call_args["y"] == 240.0


@pytest.mark.asyncio
async def test_cdp_click_default_dpr(conn):
    conn.send_action = AsyncMock(return_value={
        "type": "result", "task_id": "t1", "status": "success", "data": {},
    })
    tool = _by_name(create_browser_tools(conn, vlm_model=None, viewport_info={}), "cdp_click")
    await tool(x=100.0, y=200.0)

    call_args = conn.send_action.call_args[0][0]
    assert call_args["x"] == 100.0
    assert call_args["y"] == 200.0


# ---------------------------------------------------------------------------
# 新增：ToolBase 语义与权限检查
# ---------------------------------------------------------------------------


def test_tool_registry_completeness(conn):
    """工厂应返回 13 个工具，且 name 唯一。"""
    tools = create_browser_tools(conn, vlm_model=None, viewport_info={})
    names = [t.name for t in tools]
    assert len(names) == 13
    assert len(set(names)) == 13  # 无重名
    expected = {
        "parse_page", "get_element_info", "extract_content",
        "click_element", "input_text", "scroll_page", "scroll_element",
        "navigate", "go_back", "wait", "screenshot_analyze",
        "cdp_click", "done",
    }
    assert set(names) == expected


def test_read_only_flags(conn):
    """只读工具应正确标记 is_read_only。"""
    tools = {t.name: t for t in create_browser_tools(conn, vlm_model=None, viewport_info={})}
    read_only = {"parse_page", "get_element_info", "extract_content", "wait", "screenshot_analyze", "done"}
    for name, tool in tools.items():
        if name in read_only:
            assert tool.is_read_only is True, f"{name} 应为只读"
        else:
            assert tool.is_read_only is False, f"{name} 应为非只读"


def test_input_schema_declared(conn):
    """每个工具都应声明了 input_schema（JSON schema dict）。"""
    for tool in create_browser_tools(conn, vlm_model=None, viewport_info={}):
        assert isinstance(tool.input_schema, dict)
        assert tool.input_schema.get("type") == "object"
        assert "properties" in tool.input_schema
