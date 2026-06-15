# agent/agent.py
"""BrowserAgent：浏览器自动化 Agent 的核心封装。

以 Agent 为中心，组合模型、工具、状态等模块。
"""

import json
import re

from agentscope.agent import Agent
from agentscope.tool import Toolkit, FunctionTool
from agentscope.message import UserMsg
from agentscope.event import EventType
from agentscope.state import AgentState
from agentscope.permission import PermissionContext, PermissionMode

from browser.connection import BrowserConnection
from browser.tools import create_browser_tools
from agent.model import create_model
from agent.prompts import SYSTEM_PROMPT
from logger import get_logger

log = get_logger("agent")


class BrowserAgent:
    """浏览器自动化 Agent。

    组合：
    - LLM/VLM 模型
    - 浏览器工具集
    - Agent 状态（权限）
    """

    def __init__(self, config: dict):
        self._config = config
        self._conn = BrowserConnection()
        self._viewport_info: dict = {}
        self._busy = False
        self._agent: Agent | None = None
        self._current_ws = None

    @property
    def conn(self) -> BrowserConnection:
        """浏览器连接实例。"""
        return self._conn

    @property
    def viewport_info(self) -> dict:
        """当前视口信息。"""
        return self._viewport_info

    def init(self):
        """初始化 Agent（创建模型、注册工具、构建 agentscope Agent 实例）。

        幂等操作：重复调用不会重建。
        """
        if self._agent is not None:
            return

        llm_model = create_model(self._config["llm"], role="LLM")
        vlm_model = create_model(self._config["vlm"], role="VLM")

        # 创建并注册浏览器工具
        tool_functions = create_browser_tools(
            self._conn, vlm_model, self._viewport_info,
        )
        tool_objects = [FunctionTool(fn) for fn in tool_functions.values()]
        toolkit = Toolkit(tools=tool_objects)
        
        # 初始化状态，允许工具调用（绕过权限检查）
        state = AgentState(
            permission_context=PermissionContext(mode=PermissionMode.BYPASS),
        )

        self._agent = Agent(
            name="browser_agent",
            model=llm_model,
            toolkit=toolkit,
            state=state,
            system_prompt=SYSTEM_PROMPT,
        )
        log.info("BrowserAgent 初始化完成，挂载 %d 个工具", len(tool_functions))

    def attach_ws(self, ws):
        """绑定 WebSocket 连接（支持重连）。"""
        old_ws = self._current_ws
        self._current_ws = ws
        self._conn.set_ws(ws)
        if old_ws is not None:
            log.info("WebSocket 重连，已更新引用")
        else:
            log.info("WebSocket 已绑定")

    @staticmethod
    def _parse_reflection(text: str) -> dict | None:
        """从 LLM 文本输出中提取 reflection JSON。"""
        match = re.search(r'\{[^{}]*"evaluation_previous_goal"[^{}]*\}', text, re.DOTALL)
        if not match:
            return None
        try:
            data = json.loads(match.group())
            return {
                "evaluation_previous_goal": data.get("evaluation_previous_goal", ""),
                "memory": data.get("memory", ""),
                "next_goal": data.get("next_goal", ""),
            }
        except json.JSONDecodeError:
            return None

    async def run(self, text: str):
        """执行用户指令，流式返回事件字典。

        Yields:
            dict: 流式事件，包含 type 和 content/error/event 字段。
        """
        if self._busy:
            yield {"type": "stream", "content": "[BUSY] Agent 正在工作中..."}
            return

        self._busy = True
        log.info("Agent 收到指令: %.100s", text)
        _tool_calls: dict[str, dict] = {}
        _step_index = 0
        _text_buf = ""

        try:
            # 推送初始 thinking 状态
            yield {
                "type": "event",
                "event": {"type": "activity_status", "data": {"status": "thinking"}},
            }

            async for evt in self._agent.reply_stream(
                [UserMsg(name="user", content=text)]
            ):

                if evt.type == EventType.TEXT_BLOCK_DELTA:
                    _text_buf += evt.delta
                    yield {"type": "stream", "content": evt.delta}

                elif evt.type == EventType.TOOL_CALL_START:
                    # 在工具调用前推送 reflection
                    reflection = self._parse_reflection(_text_buf)
                    if reflection:
                        yield {
                            "type": "event",
                            "event": {"type": "reflection", "data": reflection, "timestamp": 0},
                        }
                    _text_buf = ""

                    # 推送 executing 状态
                    yield {
                        "type": "event",
                        "event": {"type": "activity_status", "data": {"status": "executing"}},
                    }

                    tid = evt.tool_call_id
                    _tool_calls[tid] = {
                        "name": evt.tool_call_name,
                        "args_buf": "",
                        "result_buf": "",
                        "step": _step_index,
                    }
                    _step_index += 1
                    yield {
                        "type": "event",
                        "event": {
                            "type": "step",
                            "data": {
                                "action": evt.tool_call_name,
                                "step": _tool_calls[tid]["step"],
                                "status": "running",
                            },
                            "timestamp": 0,
                        },
                    }

                elif evt.type == EventType.TOOL_CALL_DELTA:
                    tc = _tool_calls.get(evt.tool_call_id)
                    if tc:
                        tc["args_buf"] += evt.delta

                elif evt.type == EventType.TOOL_RESULT_TEXT_DELTA:
                    tc = _tool_calls.get(evt.tool_call_id)
                    if tc:
                        tc["result_buf"] += evt.delta

                elif evt.type == EventType.TOOL_RESULT_END:
                    tc = _tool_calls.get(evt.tool_call_id)
                    if tc:
                        try:
                            parsed_args = json.loads(tc["args_buf"]) if tc["args_buf"] else {}
                        except (json.JSONDecodeError, TypeError):
                            parsed_args = tc["args_buf"]
                        status = "done" if str(evt.state) == "success" else "error"
                        yield {
                            "type": "event",
                            "event": {
                                "type": "step",
                                "data": {
                                    "action": tc["name"],
                                    "step": tc["step"],
                                    "status": status,
                                    "input": parsed_args,
                                    "output": tc["result_buf"],
                                },
                                "timestamp": 0,
                            },
                        }

                    # 工具调用结束后推送 thinking 状态
                    yield {
                        "type": "event",
                        "event": {"type": "activity_status", "data": {"status": "thinking"}},
                    }

            # 流式结束后推送最终 reflection
            reflection = self._parse_reflection(_text_buf)
            if reflection:
                yield {
                    "type": "event",
                    "event": {"type": "reflection", "data": reflection, "timestamp": 0},
                }

            yield {"type": "stream", "content": "[DONE]"}
            yield {
                "type": "event",
                "event": {"type": "activity_status", "data": {"status": "done"}},
            }
            log.info("Agent 执行完成")
        except Exception as e:
            log.error("Agent 执行错误: %s", e, exc_info=True)
            yield {
                "type": "event",
                "event": {"type": "activity_status", "data": {"status": "error"}},
            }
            yield {"type": "error", "message": f"Agent error: {e}"}
        finally:
            self._busy = False
