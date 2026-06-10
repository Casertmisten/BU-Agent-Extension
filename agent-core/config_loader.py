# config_loader.py
"""加载 config.yaml 并替换环境变量。"""

import os
import re
from pathlib import Path

import yaml


def _substitute_env_vars(value):
    """将 ${VAR_NAME} 替换为对应的环境变量值。"""
    if isinstance(value, str):
        return re.sub(
            r"\$\{(\w+)\}",
            lambda m: os.environ.get(m.group(1), m.group(0)),
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
    return _substitute_env_vars(config)
