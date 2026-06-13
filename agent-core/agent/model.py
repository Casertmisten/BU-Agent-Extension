# agent/model.py
"""模型工厂：根据配置创建 agentscope 模型实例。"""

from agentscope.model import DashScopeChatModel, OpenAIChatModel
from agentscope.credential import DashScopeCredential, OpenAICredential
from logger import get_logger

log = get_logger("model")


def create_model(config: dict, role: str | None = None):
    """根据配置字典创建模型实例。

    Args:
        config: 包含 provider、model、api_key 的字典。
        role: 模型角色标识（如 LLM/VLM），仅用于日志。

    Returns:
        agentscope 模型实例。
    """
    provider = config["provider"]
    model_name = config["model"]
    api_key = config["api_key"]
    role_tag = f"[{role}] " if role else ""

    if provider == "openai":
        log.info("%s加载模型: %s", role_tag, model_name)
        return OpenAIChatModel(
            credential=OpenAICredential(api_key=api_key),
            model=model_name,
        )
    elif provider == "dashscope":
        log.info("%s加载模型: %s", role_tag, model_name)
        return DashScopeChatModel(
            credential=DashScopeCredential(api_key=api_key),
            model=model_name,
        )
    else:
        raise ValueError(
            f"不支持的 provider: {provider}。"
            f"请在 agent/model.py 中添加支持。当前支持: openai, dashscope"
        )
