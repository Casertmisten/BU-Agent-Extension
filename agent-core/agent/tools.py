# agent/tools.py
"""工具注册中心：集中管理注册到 Agent 的工具。

将"工具如何创建/组装"从 Agent 文件中剥离：
- Agent 只通过 create_toolkit() 拿到一个构建好的 Toolkit，
- 具体引入哪些工具（浏览器工具、未来的其他工具）、如何拼装，
  都收敛在本模块，便于后续扩展与维护。
"""

import os

from agentscope.tool import Toolkit
from agentscope.skill import LocalSkillLoader

from browser.connection import BrowserConnection
from browser.tools import create_browser_tools
from logger import get_logger

log = get_logger("tools")


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

    # 注册技能：从配置的多目录扫描 SKILL.md（递归子目录）。
    # scan_subdir=True：每个技能位于 <dir>/<skill-name>/SKILL.md。
    skill_dirs = config.get("skills", {}).get("dirs", [])
    skills_or_loaders = []
    for d in skill_dirs:
        if os.path.isdir(d):
            skills_or_loaders.append(
                LocalSkillLoader(directory=d, scan_subdir=True)
            )
        else:
            log.warning("技能目录不存在，已跳过: %s", d)

    toolkit = Toolkit(
        tools=tool_objects,
        skills_or_loaders=skills_or_loaders,
    )
    log.info("Toolkit 构建完成，挂载 %d 个工具", len(tool_objects))
    return toolkit
