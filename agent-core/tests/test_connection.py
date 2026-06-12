# tests/test_connection.py
import asyncio
import json
import pytest
from unittest.mock import AsyncMock
from browser.connection import BrowserConnection


@pytest.fixture
def conn():
    return BrowserConnection()


@pytest.mark.asyncio
async def test_send_action_sends_json_with_task_id(conn):
    mock_ws = AsyncMock()
    conn.set_ws(mock_ws)

    task = asyncio.create_task(conn.send_action({"action": "click", "target_id": "agent-05"}))
    await asyncio.sleep(0.01)

    mock_ws.send.assert_called_once()
    sent = json.loads(mock_ws.send.call_args[0][0])
    assert sent["type"] == "action"
    assert sent["action"] == "click"
    assert sent["target_id"] == "agent-05"
    assert "task_id" in sent

    conn.handle_result({"type": "result", "task_id": sent["task_id"], "status": "success", "data": {}})
    result = await task
    assert result["status"] == "success"


@pytest.mark.asyncio
async def test_handle_result_raises_on_error(conn):
    mock_ws = AsyncMock()
    conn.set_ws(mock_ws)

    task = asyncio.create_task(conn.send_action({"action": "click", "target_id": "agent-99"}))
    await asyncio.sleep(0.01)

    sent = json.loads(mock_ws.send.call_args[0][0])
    conn.handle_result({"type": "result", "task_id": sent["task_id"], "status": "error", "error": "Element not found"})

    with pytest.raises(Exception, match="Element not found"):
        await task


@pytest.mark.asyncio
async def test_handle_result_ignores_unknown_task_id(conn):
    conn.handle_result({"type": "result", "task_id": "nonexistent", "status": "success", "data": {}})


def test_viewport_default(conn):
    assert conn.viewport_info == {}


def test_update_viewport(conn):
    conn.update_viewport({"dpr": 2.0, "width": 1280, "height": 720})
    assert conn.viewport_info["dpr"] == 2.0
    assert conn.viewport_info["width"] == 1280


@pytest.mark.asyncio
async def test_send_action_raises_when_no_ws():
    conn = BrowserConnection()
    with pytest.raises(RuntimeError, match="WebSocket not connected"):
        await conn.send_action({"action": "parse_dom"})


@pytest.mark.asyncio
async def test_disconnect_cancels_pending():
    """断连时 pending Future 应该收到 ConnectionError。"""
    mock_ws = AsyncMock()
    conn = BrowserConnection()
    conn.set_ws(mock_ws)

    task = asyncio.create_task(conn.send_action({"action": "parse_dom"}))
    await asyncio.sleep(0.01)

    assert len(conn._pending) == 1
    conn.disconnect()

    with pytest.raises(ConnectionError, match="WebSocket 断开"):
        await task

    assert len(conn._pending) == 0
    assert conn._ws is None


@pytest.mark.asyncio
async def test_disconnect_no_pending():
    """没有 pending 请求时 disconnect 不报错。"""
    conn = BrowserConnection()
    conn.disconnect()  # 不应抛异常
    assert len(conn._pending) == 0
