# tests/test_server.py
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from browser.connection import BrowserConnection
from browser.protocol import validate_message


def test_import_server():
    from server import create_agent, handle_client
    assert callable(create_agent)
    assert callable(handle_client)


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


def test_create_agent_has_all_tools():
    from server import create_agent
    conn = BrowserConnection()
    mock_llm = MagicMock()
    mock_vlm = MagicMock()
    viewport_info = {}

    agent = create_agent(conn, mock_vlm, viewport_info, mock_llm)
    assert agent is not None
