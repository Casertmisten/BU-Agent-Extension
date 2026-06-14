# tests/test_config_loader.py
import os
import pytest
from config_loader import load_config


def test_load_config_reads_yaml(tmp_path):
    config_file = tmp_path / "config.yaml"
    config_file.write_text("""
llm:
  provider: openai
  model: gpt-4o
  api_key: test-key
vlm:
  provider: openai
  model: gpt-4o
  api_key: test-key
server:
  host: localhost
  port: 8765
  heartbeat_interval: 30
""")
    config = load_config(str(config_file))
    assert config["llm"]["provider"] == "openai"
    assert config["llm"]["model"] == "gpt-4o"
    assert config["server"]["port"] == 8765


def test_load_config_env_var_substitution(tmp_path):
    os.environ["TEST_BU_KEY"] = "env-key-123"
    config_file = tmp_path / "config.yaml"
    config_file.write_text("""
llm:
  provider: openai
  model: gpt-4o
  api_key: ${TEST_BU_KEY}
""")
    config = load_config(str(config_file))
    assert config["llm"]["api_key"] == "env-key-123"
    del os.environ["TEST_BU_KEY"]


def test_skills_config_has_default_dir():
    """config.yaml 应包含 skills.dirs，默认含 ./skills。"""
    config = load_config("config.yaml")
    assert "skills" in config
    assert "./skills" in config["skills"]["dirs"]
