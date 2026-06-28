# agent/tools.py
"""工具注册中心：集中管理注册到 Agent 的工具。

将"工具如何创建/组装"从 Agent 文件中剥离：
- Agent 只通过 create_toolkit() 拿到一个构建好的 Toolkit，
- 具体引入哪些工具（浏览器工具、未来的其他工具）、如何拼装，
  都收敛在本模块，便于后续扩展与维护。
"""

import os

from agentscope.tool import Toolkit
from agentscope.skill import LocalSkillLoader, SkillLoaderBase

from browser.connection import BrowserConnection
from browser.tools import create_browser_tools
from logger import get_logger

log = get_logger("tools")


def create_skill_loaders(config: dict) -> list[SkillLoaderBase]:
    """根据配置构建技能加载器列表。

    单独抽出以便 ``list_skills`` 直接查询 loader（公开稳定 API），避免
    依赖 Toolkit 的私有方法 ``_get_available_skills``。

    Args:
        config: 全局配置字典（读取 skills.dirs）。

    Returns:
        已存在的技能目录对应的 SkillLoaderBase 列表。
    """
    skill_dirs = config.get("skills", {}).get("dirs", [])
    loaders: list[SkillLoaderBase] = []
    for d in skill_dirs:
        if os.path.isdir(d):
            loaders.append(LocalSkillLoader(directory=d, scan_subdir=True))
        else:
            log.warning("技能目录不存在，已跳过: %s", d)
    return loaders


def create_toolkit(
    config: dict,
    conn: BrowserConnection,
    vlm_model,
    viewport_info: dict,
) -> Toolkit:
    """构建并返回注册好工具与技能的 Toolkit。

    Args:
        config: 全局配置字典（读取 skills.dirs 等条目）。
        conn: 浏览器连接实例。
        vlm_model: VLM 模型实例（供截图分析等视觉工具使用）。
        viewport_info: 视口信息字典（供 CDP 坐标换算等使用）。

    Returns:
        组装完成的 Toolkit。
    """
    # 创建浏览器工具（已是 list[ToolBase]，无需再包 FunctionTool）
    dom_strategy = config.get("browser", {}).get("dom_strategy", "ax")
    tool_objects = create_browser_tools(
        conn, vlm_model, viewport_info, dom_strategy=dom_strategy,
    )

    toolkit = Toolkit(
        tools=tool_objects,
        skills_or_loaders=create_skill_loaders(config),
    )
    log.info("Toolkit 构建完成，挂载 %d 个工具", len(tool_objects))
    return toolkit
