# config_loader.py
"""加载 config.yaml 并替换环境变量。"""

import os
import re
from pathlib import Path

import yaml


def _replace_match(match: re.Match[str]) -> str:
    """将单个环境变量占位符替换为实际值。"""
    var = match.group(1)
    default = match.group(3)  # None 如果没有 :- 部分
    return os.environ.get(var, default if default is not None else match.group(0))


def _substitute_env_vars(value: object) -> object:
    """将 ${VAR_NAME} 或 ${VAR_NAME:-default} 替换为对应的环境变量值。"""
    if isinstance(value, str):
        return re.sub(
            r"\$\{(\w+)(:-([^}]*))?\}",
            _replace_match,
            value,
        )
    if isinstance(value, dict):
        return {k: _substitute_env_vars(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_substitute_env_vars(item) for item in value]
    return value


def load_config(config_path: str = "config.yaml") -> dict:
    """加载 config.yaml 并替换环境变量。"""
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")
    with open(path) as f:
        config = yaml.safe_load(f)
    result = _substitute_env_vars(config)
    assert isinstance(result, dict)
    return result
