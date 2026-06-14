# agent/agent.py
"""BrowserAgent：浏览器自动化 Agent 的核心封装。

以 Agent 为中心，组合模型、工具、状态等模块。
"""

import json
import re

from agentscope.agent import Agent
from agentscope.message import UserMsg
from agentscope.event import EventType
from agentscope.state import AgentState
from agentscope.permission import PermissionContext, PermissionMode

from browser.connection import BrowserConnection
from agent.model import create_model
from agent.prompts import SYSTEM_PROMPT
from agent.tools import create_toolkit
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

        # 构建工具集（浏览器工具 + 技能），细节收敛在 agent.tools
        toolkit = create_toolkit(
            self._config, self._conn, vlm_model, self._viewport_info,
        )

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
        log.info("BrowserAgent 初始化完成")

    async def list_skills(self) -> list[dict]:
        """返回当前注册的技能清单 [{name, description}]，供前端展示。

        直接委托给 toolkit，技能集是全局静态的，与会话无关。
        """
        if self._agent is None:
            return []
        skills = await self._agent.toolkit._get_available_skills()
        return [
            {"name": s.name, "description": s.description}
            for s in skills.values()
        ]

    def reset_context(self) -> None:
        """新建会话：重建 Agent 实例以彻底隔离上下文。

        agentscope 的工具调用在独立的 gather_task（asyncio.create_task）中执行，
        _current_task.cancel() 不会级联到它。若仅清空 state.context，正在运行的
        orphan 工具（如 VLM 分析）完成后会通过 _save_to_context 把旧工具结果写回
        已被清空的 context，污染新会话。重建 Agent 实例后，orphan 仍持有旧 Agent
        引用（self 绑定），写入旧 state（随旧实例被丢弃），新 Agent 的 state 全新
        且干净。

        model/toolkit 为重资产，复用旧实例（不重新加载/不重新注册）；
        permission_context 保留（用户级工具授权跨会话有效）。
        """
        if self._agent is not None:
            old = self._agent
            self._agent = Agent(
                name="browser_agent",
                system_prompt=SYSTEM_PROMPT,
                model=old.model,
                toolkit=old.toolkit,
                state=AgentState(
                    permission_context=old.state.permission_context,
                ),
            )

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
    def _drain_reflection(text: str) -> tuple[dict | None, str]:
        """从文本中分离 reflection JSON 与剩余回复文本。

        reflection 只显示在工具步骤卡片，不应进入回复气泡；剩余文本作为给用户的回复。
        返回 (reflection_dict 或 None, remaining_text)。
        """
        match = re.search(r'\{[^{}]*"evaluation_previous_goal"[^{}]*\}', text, re.DOTALL)
        if not match:
            return None, text
        try:
            data = json.loads(match.group())
        except json.JSONDecodeError:
            return None, text
        reflection = {
            "evaluation_previous_goal": data.get("evaluation_previous_goal", ""),
            "memory": data.get("memory", ""),
            "next_goal": data.get("next_goal", ""),
        }
        remaining = (text[:match.start()] + text[match.end():]).strip()
        return reflection, remaining

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
        _total_input_tokens = 0
        _total_output_tokens = 0

        try:
            # 推送初始 thinking 状态
            yield {
                "type": "event",
                "event": {"type": "activity_status", "data": {"status": "thinking"}},
            }

            async for evt in self._agent.reply_stream(
                [UserMsg(name="user", content=text)]
            ):
                if evt.type == EventType.MODEL_CALL_END:
                    # 累加本轮对话的 token 消耗，结束时一次性发送
                    it = getattr(evt, "input_tokens", None)
                    ot = getattr(evt, "output_tokens", None)
                    if isinstance(it, int):
                        _total_input_tokens += it
                    if isinstance(ot, int):
                        _total_output_tokens += ot
                elif evt.type == EventType.TEXT_BLOCK_DELTA:
                    # 缓冲文本，不立即推送：需在工具调用/流结束时区分 reflection（进步骤卡片）
                    # 与回复文本（进气泡），避免 reflection JSON 显示在回复气泡
                    _text_buf += evt.delta

                elif evt.type == EventType.TOOL_CALL_START:
                    # 在工具调用前分离 reflection 与回复文本
                    reflection, remaining = self._drain_reflection(_text_buf)
                    if reflection:
                        yield {
                            "type": "event",
                            "event": {"type": "reflection", "data": reflection, "timestamp": 0},
                        }
                    if remaining:
                        yield {"type": "stream", "content": remaining}
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
                    # done 是元工具(标记完成并转发汇报)，其 text 应进回复气泡，不显示工具步骤卡片
                    if evt.tool_call_name != "done":
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
                    is_done = tc is not None and tc["name"] == "done"
                    if is_done:
                        # done 的 text 是给用户的最终汇报，推送到回复气泡，不进工具步骤卡片
                        try:
                            parsed_args = json.loads(tc["args_buf"]) if tc["args_buf"] else {}
                        except (json.JSONDecodeError, TypeError):
                            parsed_args = {}
                        if isinstance(parsed_args, dict) and parsed_args.get("text"):
                            yield {"type": "stream", "content": parsed_args["text"]}
                    elif tc:
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
                    # 非 done 工具结束后切回 thinking；done 标志任务结束
                    if not is_done:
                        yield {
                            "type": "event",
                            "event": {"type": "activity_status", "data": {"status": "thinking"}},
                        }

            # 流式结束后分离剩余文本：reflection 进步骤卡片，回复文本进气泡
            reflection, remaining = self._drain_reflection(_text_buf)
            if reflection:
                yield {
                    "type": "event",
                    "event": {"type": "reflection", "data": reflection, "timestamp": 0},
                }
            if remaining:
                yield {"type": "stream", "content": remaining}

            # 发送本轮对话的 token 消耗汇总（在 [DONE] 之前，前端定稿前收到）
            yield {
                "type": "event",
                "event": {
                    "type": "token_usage",
                    "data": {
                        "input": _total_input_tokens,
                        "output": _total_output_tokens,
                    },
                    "timestamp": 0,
                },
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
