# tests/test_protocol.py
import pytest
from browser.protocol import validate_message, MSG_TYPES


def test_validate_action():
    assert validate_message({"type": "action", "action": "click", "target_id": "agent-05", "task_id": "abc"}) is True


def test_validate_result():
    assert validate_message({"type": "result", "task_id": "abc", "status": "success", "data": {}}) is True


def test_validate_heartbeat():
    assert validate_message({"type": "heartbeat", "ts": 1718000000}) is True


def test_validate_page_ready():
    assert validate_message({"type": "page_ready", "url": "https://example.com", "tab_id": 123, "viewport": {"dpr": 2.0}}) is True


def test_validate_stream():
    assert validate_message({"type": "stream", "content": "Thinking..."}) is True


def test_validate_mode_change():
    assert validate_message({"type": "mode_change", "mode": "ai"}) is True


def test_validate_user_message():
    assert validate_message({"type": "user_message", "content": "Search for weather"}) is True


def test_reject_unknown_type():
    with pytest.raises(ValueError, match="Unknown message type"):
        validate_message({"type": "unknown_type"})


def test_reject_missing_type():
    with pytest.raises(ValueError, match="Missing 'type' field"):
        validate_message({"action": "click"})


def test_msg_types_complete():
    expected = {"action", "result", "heartbeat", "page_ready", "stream", "mode_change", "user_message", "browser_state", "tab_change"}
    assert expected == MSG_TYPES
