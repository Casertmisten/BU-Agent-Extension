# tests/test_tools.py
import json
import pytest
from unittest.mock import AsyncMock, MagicMock
from browser.connection import BrowserConnection
from browser.tools import create_browser_tools


@pytest.fixture
def conn():
    c = BrowserConnection()
    c.set_ws(AsyncMock())
    return c


@pytest.mark.asyncio
async def test_parse_dom(conn):
    conn.send_action = AsyncMock(return_value={
        "type": "result", "task_id": "t1", "status": "success",
        "data": {"elements": [{"id": "agent-00", "tag": "button", "text": "Submit"}]},
    })
    tools = create_browser_tools(conn, vlm_model=None, viewport_info={})
    result = await tools["parse_dom"]()
    assert "agent-00" in result.output


@pytest.mark.asyncio
async def test_get_element_info(conn):
    conn.send_action = AsyncMock(return_value={
        "type": "result", "task_id": "t1", "status": "success",
        "data": {"tag": "input", "type": "text", "visible": True},
    })
    tools = create_browser_tools(conn, vlm_model=None, viewport_info={})
    result = await tools["get_element_info"]("agent-05")
    assert "input" in result.output


@pytest.mark.asyncio
async def test_click_element(conn):
    conn.send_action = AsyncMock(return_value={
        "type": "result", "task_id": "t1", "status": "success", "data": {},
    })
    tools = create_browser_tools(conn, vlm_model=None, viewport_info={})
    result = await tools["click_element"]("agent-05")
    assert "success" in result.output.lower()


@pytest.mark.asyncio
async def test_input_text(conn):
    conn.send_action = AsyncMock(return_value={
        "type": "result", "task_id": "t1", "status": "success", "data": {},
    })
    tools = create_browser_tools(conn, vlm_model=None, viewport_info={})
    result = await tools["input_text"]("agent-12", "hello world")
    assert "success" in result.output.lower()


@pytest.mark.asyncio
async def test_scroll_page(conn):
    conn.send_action = AsyncMock(return_value={
        "type": "result", "task_id": "t1", "status": "success", "data": {},
    })
    tools = create_browser_tools(conn, vlm_model=None, viewport_info={})
    result = await tools["scroll_page"]("down", 300)
    assert "success" in result.output.lower()


@pytest.mark.asyncio
async def test_navigate(conn):
    conn.send_action = AsyncMock(return_value={
        "type": "result", "task_id": "t1", "status": "success", "data": {},
    })
    tools = create_browser_tools(conn, vlm_model=None, viewport_info={})
    result = await tools["navigate"]("https://example.com")
    assert "success" in result.output.lower()


@pytest.mark.asyncio
async def test_wait(conn):
    conn.send_action = AsyncMock(return_value={
        "type": "result", "task_id": "t1", "status": "success", "data": {},
    })
    tools = create_browser_tools(conn, vlm_model=None, viewport_info={})
    result = await tools["wait"](2)
    assert "success" in result.output.lower()


@pytest.mark.asyncio
async def test_screenshot_analyze(conn):
    mock_vlm = AsyncMock()
    mock_vlm.return_value = MagicMock(content="Page shows a login form with email and password fields.")
    conn.send_action = AsyncMock(return_value={
        "type": "result", "task_id": "t1", "status": "success",
        "data": {"image": "iVBORw0KGgoAAAANSUhEUg=="},
    })
    tools = create_browser_tools(conn, vlm_model=mock_vlm, viewport_info={})
    result = await tools["screenshot_analyze"]()
    assert "login form" in result.output.lower()


@pytest.mark.asyncio
async def test_cdp_click_coordinate_conversion(conn):
    conn.send_action = AsyncMock(return_value={
        "type": "result", "task_id": "t1", "status": "success", "data": {},
    })
    # DPR 2.0: image pixels 640 -> CSS pixels 320
    tools = create_browser_tools(conn, vlm_model=None, viewport_info={"dpr": 2.0})
    await tools["cdp_click"](640.0, 480.0)

    call_args = conn.send_action.call_args[0][0]
    assert call_args["x"] == 320.0
    assert call_args["y"] == 240.0


@pytest.mark.asyncio
async def test_cdp_click_default_dpr(conn):
    conn.send_action = AsyncMock(return_value={
        "type": "result", "task_id": "t1", "status": "success", "data": {},
    })
    tools = create_browser_tools(conn, vlm_model=None, viewport_info={})
    await tools["cdp_click"](100.0, 200.0)

    call_args = conn.send_action.call_args[0][0]
    assert call_args["x"] == 100.0
    assert call_args["y"] == 200.0
