# agent/model.py
"""模型工厂：根据配置创建 agentscope 模型实例。

遵循 agentscope v2 规范：通过 ``credential.get_chat_model_class()`` 让
Credential 自行决定对应的 ChatModel 类，工厂只负责 credential 的装配，
不再硬编码 provider → ChatModel 的映射，新增 provider 时无需改动本模块。
"""

from agentscope.credential import (
    DashScopeCredential,
    OpenAICredential,
)
from logger import get_logger

log = get_logger("model")

# provider 配置值 → Credential 工厂。
# custom_local 复用 OpenAICredential（OpenAI 兼容接口），额外注入 base_url。
_CREDENTIAL_BUILDERS = {
    "openai": lambda cfg: OpenAICredential(api_key=cfg["api_key"]),
    "dashscope": lambda cfg: DashScopeCredential(api_key=cfg["api_key"]),
    "custom_local": lambda cfg: OpenAICredential(
        api_key=cfg.get("api_key", "none"),
        base_url=cfg["base_url"],
    ),
}


def _build_credential(config: dict):
    """根据 provider 创建对应的 Credential 实例。"""
    provider = config["provider"]
    builder = _CREDENTIAL_BUILDERS.get(provider)
    if builder is None:
        supported = ", ".join(sorted(_CREDENTIAL_BUILDERS))
        raise ValueError(
            f"不支持的 provider: {provider}。当前支持: {supported}"
        )
    return builder(config)


def create_model(config: dict, role: str | None = None):
    """根据配置字典创建模型实例。

    Args:
        config: 包含 provider、model、api_key 的字典。
        role: 模型角色标识（如 LLM/VLM），仅用于日志。

    Returns:
        agentscope ChatModelBase 实例。
    """
    provider = config["provider"]
    model_name = config["model"]
    role_tag = f"[{role}] " if role else ""

    credential = _build_credential(config)
    # 让 credential 决定对应的 ChatModel 类，而非在此硬编码 import
    model_cls = credential.get_chat_model_class()

    log.info("%s加载模型: %s（provider=%s）", role_tag, model_name, provider)
    return model_cls(credential=credential, model=model_name)
