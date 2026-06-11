# tests/test_server.py
import json
import pytest
from unittest.mock import AsyncMock


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
