# tests/test_model.py
import pytest
from agent.model import create_model


def test_create_model_openai():
    model = create_model({"provider": "openai", "model": "gpt-4o", "api_key": "test-key"})
    assert model is not None


def test_create_model_dashscope():
    model = create_model({"provider": "dashscope", "model": "qwen-plus", "api_key": "test-key"})
    assert model is not None


def test_create_model_unsupported():
    with pytest.raises(ValueError, match="不支持的 provider"):
        create_model({"provider": "unknown", "model": "x", "api_key": "k"})
