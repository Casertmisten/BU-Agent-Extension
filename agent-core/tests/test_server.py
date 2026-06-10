# tests/test_server.py
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from browser.connection import BrowserConnection
from browser.protocol import validate_message


def test_import_server():
    from server import handle_client, _ServerState
    assert callable(handle_client)
    assert _ServerState is not None


def test_create_model_openai():
    from server import _create_model
    model = _create_model({"provider": "openai", "model": "gpt-4o", "api_key": "test-key"})
    assert model is not None


def test_create_model_dashscope():
    from server import _create_model
    model = _create_model({"provider": "dashscope", "model": "qwen-plus", "api_key": "test-key"})
    assert model is not None


def test_create_model_unsupported():
    from server import _create_model
    with pytest.raises(ValueError, match="Unsupported provider"):
        _create_model({"provider": "unknown", "model": "x", "api_key": "k"})


def test_server_state_init_agent():
    """测试 _ServerState 单次初始化 Agent。"""
    from server import _ServerState
    state = _ServerState()
    assert state.agent is None

    config = {
        "llm": {"provider": "dashscope", "model": "qwen-plus", "api_key": "test-key"},
        "vlm": {"provider": "dashscope", "model": "qwen-plus", "api_key": "test-key"},
    }
    state.init_agent(config)
    assert state.agent is not None
    # 二次调用不会重建
    old_agent = state.agent
    state.init_agent(config)
    assert state.agent is old_agent


def test_server_state_attach_ws():
    """测试 attach_ws 更新 conn 的 WebSocket 引用。"""
    from server import _ServerState
    state = _ServerState()
    mock_ws = AsyncMock()
    state.attach_ws(mock_ws)
    assert state._current_ws is mock_ws
    assert state.conn._ws is mock_ws
