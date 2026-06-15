# agent/model.py
"""模型工厂：根据配置创建 agentscope 模型实例。"""

from typing import Literal, Type

from pydantic import Field, ConfigDict

from agentscope.model import DashScopeChatModel, OpenAIChatModel
from agentscope.credential import (
    CredentialBase,
    DashScopeCredential,
    OpenAICredential,
    CredentialFactory,
)
from logger import get_logger

log = get_logger("model")


# ---------------------------------------------------------------------------
# 自定义本地模型凭证（OpenAI 兼容协议，如 vLLM / LM Studio 等）
# ---------------------------------------------------------------------------

class CustomLocalCredential(CredentialBase):
    """自定义本地模型提供商的凭证。"""

    model_config = ConfigDict(title="自定义本地模型")

    type: Literal["custom_local_credential"] = "custom_local_credential"

    base_url: str = Field(
        description="本地模型服务的 API 地址，如 http://localhost:8000/v1",
    )

    api_key: str = Field(
        default="none",
        description="API 密钥，部分本地服务不需要可留空。",
    )

    @classmethod
    def get_chat_model_class(cls) -> Type[OpenAIChatModel]:
        return OpenAIChatModel


# 注册到 AgentScope 工厂
CredentialFactory.register_credential(CustomLocalCredential)


# ---------------------------------------------------------------------------
# 模型工厂
# ---------------------------------------------------------------------------

def create_model(config: dict, role: str = ""):
    """根据配置字典创建模型实例。

    Args:
        config: 包含 provider、model、api_key 等字段的字典。
        role: 模型角色标识，如 "LLM"、"VLM"。

    Returns:
        agentscope 模型实例。
    """
    provider = config["provider"]
    model_name = config["model"]
    prefix = f"[{role}] " if role else ""

    if provider == "openai":
        log.info("%s加载模型: %s", prefix, model_name)
        return OpenAIChatModel(
            credential=OpenAICredential(api_key=config["api_key"]),
            model=model_name,
        )
    elif provider == "dashscope":
        log.info("%s加载模型: %s", prefix, model_name)
        return DashScopeChatModel(
            credential=DashScopeCredential(api_key=config["api_key"]),
            model=model_name,
        )
    elif provider == "custom_local":
        base_url = config["base_url"]
        log.info("%s加载本地模型: %s @ %s", prefix, model_name, base_url)
        return OpenAIChatModel(
            credential=OpenAICredential(
                api_key=config.get("api_key", "none"),
                base_url=base_url,
            ),
            model=model_name,
        )
    else:
        raise ValueError(
            f"不支持的 provider: {provider}。"
            f"当前支持: openai, dashscope, custom_local"
        )
