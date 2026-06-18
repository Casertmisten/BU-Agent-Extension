# agent/agent.py
"""BrowserAgent：浏览器自动化 Agent 的核心封装。

以 Agent 为中心，组合模型、工具、状态等模块。
"""

import json
import re

from agentscope.agent import Agent
from agentscope.message import UserMsg, ToolResultState
from agentscope.event import EventType
from agentscope.state import AgentState
from agentscope.permission import PermissionContext, PermissionMode

from browser.connection import BrowserConnection
from agent.model import create_model
from agent.prompts import SYSTEM_PROMPT
from agent.tools import create_toolkit, create_skill_loaders
from logger import get_logger

log = get_logger("agent")


class ReflectionFilter:
    """增量分离 reflection JSON 与回复文本，替代整段缓冲。

    模型每轮先输出一个 reflection JSON 块（进步骤卡片），其后才是回复文本（进气泡）。
    逐 delta 分类，避免把回复文本也一并缓冲到工具调用边界才发出（块状输出）：

    - scanning：跳过前导空白。首个非空白字符是 ``{`` → 进入 in_json；否则连同
      前导空白作为回复文本流式发出，进入 passthrough。
    - in_json：累积字符并跟踪大括号深度（忽略字符串内的 ``{}`` 与转义）。
      顶层 ``}`` 闭合后用 drain_fn 判定：成功 → 产出 reflection 并丢弃 JSON 块；
      失败 → 整块作为回复文本发出。随后进入 passthrough。
    - passthrough：后续每个 delta 立即流式发出，零缓冲。

    flush() 在 TOOL_CALL_START / 流结束时收尾：解析残余缓冲并重置状态，
    同一实例可复用于下一轮模型输出。
    """

    def __init__(self, drain_fn):
        self._drain = drain_fn
        self._reset()

    def _reset(self):
        self._hold = ""
        self._state = "scanning"   # scanning | in_json | passthrough
        self._depth = 0            # JSON 大括号深度
        self._in_string = False    # 是否处于 JSON 字符串内
        self._escape = False       # 字符串内是否转义下一字符

    def feed(self, delta: str) -> tuple[dict | None, str]:
        """处理一段 delta，返回 (reflection 或 None, 可流式发出的文本)。"""
        if self._state == "passthrough":
            return None, delta

        out: list[str] = []
        reflection: dict | None = None
        i = 0
        n = len(delta)
        while i < n and self._state != "passthrough":
            ch = delta[i]
            if self._state == "scanning":
                if ch.isspace():
                    self._hold += ch
                elif ch == "{":
                    self._state = "in_json"
                    self._depth = 1
                    self._hold = ch
                else:
                    # 不是 reflection：前导空白 + 本字符作为回复文本，进入直通
                    out.append(self._hold + ch)
                    self._hold = ""
                    self._state = "passthrough"
            else:  # in_json
                self._hold += ch
                if self._in_string:
                    if self._escape:
                        self._escape = False
                    elif ch == "\\":
                        self._escape = True
                    elif ch == '"':
                        self._in_string = False
                else:
                    if ch == '"':
                        self._in_string = True
                    elif ch == "{":
                        self._depth += 1
                    elif ch == "}":
                        self._depth -= 1
                        if self._depth == 0:
                            # JSON 闭合：判定是否 reflection
                            refl, remaining = self._drain(self._hold)
                            if refl is not None:
                                reflection = refl
                                if remaining:
                                    out.append(remaining)
                            else:
                                # 非法/非 reflection JSON，整块当文本发出
                                out.append(self._hold)
                            self._hold = ""
                            self._state = "passthrough"
            i += 1

        # 进入 passthrough 后，本段 delta 剩余部分一次性直通
        if self._state == "passthrough" and i < n:
            out.append(delta[i:])

        return reflection, "".join(out)

    def flush(self) -> tuple[dict | None, str]:
        """收尾：解析残余缓冲并重置状态，返回 (reflection 或 None, 残留文本)。"""
        if self._state == "scanning":
            self._reset()
            return None, ""
        if self._state == "in_json":
            hold = self._hold
            refl, remaining = self._drain(hold)
            self._reset()
            if refl is not None:
                return refl, remaining
            return None, hold
        self._reset()
        return None, ""


# ---------------------------------------------------------------------------
# 方案 B：done.text 是回复气泡的唯一来源（逐 token 流式）
#
# done 工具参数形如 {"success": true, "text": "..."}，其 arguments 经
# TOOL_CALL_DELTA 逐帧增量到达。下方用正则从（可能尚未闭合的）累积缓冲中
# 提取 text 字段已到达部分，解码 JSON 转义后增量推送到气泡，实现真流式
# 打字机效果，且只在 done 这一条路径产出回复文本，从结构上杜绝重复。
# ---------------------------------------------------------------------------

_DONE_TEXT_COMPLETE = re.compile(r'"text"\s*:\s*"((?:[^"\\]|\\.)*)"')
_DONE_TEXT_PARTIAL = re.compile(r'"text"\s*:\s*"((?:[^"\\]|\\.)*)$')


def _decode_json_string(raw: str) -> str:
    """解码 JSON 字符串转义（\\n \\t \\r \\" \\\\ \\/ \\b \\f \\uXXXX）。"""
    out: list[str] = []
    i = 0
    n = len(raw)
    simple = {'n': '\n', 't': '\t', 'r': '\r', '"': '"', '\\': '\\',
              '/': '/', 'b': '\b', 'f': '\f'}
    while i < n:
        c = raw[i]
        if c == '\\' and i + 1 < n:
            e = raw[i + 1]
            if e == 'u' and i + 6 <= n:
                try:
                    out.append(chr(int(raw[i + 2:i + 6], 16)))
                    i += 6
                    continue
                except ValueError:
                    pass
            out.append(simple.get(e, e))
            i += 2
        else:
            out.append(c)
            i += 1
    return ''.join(out)


def _extract_done_text(args_buf: str) -> str:
    """从（可能尚未闭合的）done 参数 JSON 中提取 text 字段已到达的解码文本。

    优先匹配已闭合的完整字符串；否则匹配尚未闭合的部分（流式中段，悬挂的
    转义符不会被捕获，留待下一帧补全）。未出现 text 字段时返回空串。
    """
    m = _DONE_TEXT_COMPLETE.search(args_buf)
    if m:
        return _decode_json_string(m.group(1))
    m = _DONE_TEXT_PARTIAL.search(args_buf)
    if m:
        return _decode_json_string(m.group(1))
    return ""


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
        # 技能加载器：用于 list_skills 直接查询（公开稳定 API），
        # 避免依赖 toolkit 的私有方法 _get_available_skills。
        # 与会话无关、全局静态，初始化时构建一次即可。
        self._skill_loaders = create_skill_loaders(config)

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

        直接查询已注册的 SkillLoader（公开 API），技能集是全局静态的，与会话无关。
        """
        seen: dict[str, dict] = {}
        for loader in self._skill_loaders:
            for skill in await loader.list_skills():
                if skill.name in seen:
                    continue
                seen[skill.name] = {
                    "name": skill.name,
                    "description": skill.description,
                }
        return list(seen.values())

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
    def _parse_reflection(text: str) -> dict | None:
        """从文本中解析 reflection JSON。

        reflection 结构固定：
        ``{"evaluation_previous_goal", "memory", "next_goal"}``，
        找不到或解析失败时返回 None。
        """
        match = re.search(r'\{[^{}]*"evaluation_previous_goal"[^{}]*\}', text, re.DOTALL)
        if not match:
            return None
        try:
            data = json.loads(match.group())
        except json.JSONDecodeError:
            return None
        return {
            "evaluation_previous_goal": data.get("evaluation_previous_goal", ""),
            "memory": data.get("memory", ""),
            "next_goal": data.get("next_goal", ""),
        }

    @classmethod
    def _drain_reflection(cls, text: str) -> tuple[dict | None, str]:
        """从文本中分离 reflection JSON 与剩余回复文本。

        reflection 只显示在工具步骤卡片，不应进入回复气泡；剩余文本作为给用户的回复。
        返回 (reflection_dict 或 None, remaining_text)。
        """
        match = re.search(r'\{[^{}]*"evaluation_previous_goal"[^{}]*\}', text, re.DOTALL)
        if not match:
            return None, text
        reflection = cls._parse_reflection(match.group())
        if reflection is None:
            return None, text
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
        # 增量分离 reflection JSON 与正文：reflection 进步骤卡片；正文不再进气泡，
        # 仅暂存为兜底——done.text 才是回复气泡的唯一来源（方案 B，逐 token 流式）
        _filter = ReflectionFilter(self._drain_reflection)
        _trailing_text: list[str] = []   # 中间步骤正文兜底：仅 done 未产出文本时回退使用
        # done 流式：已推送到气泡的 text 字符数（避免重复发送）
        _done_emitted = 0
        _done_args = ""                  # done 工具参数累积缓冲
        _done_active = False
        _done_emitted_any = False        # done 是否至少产出过一次文本（判定是否需兜底）
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
                    _total_input_tokens += evt.input_tokens
                    _total_output_tokens += evt.output_tokens
                elif evt.type == EventType.TEXT_BLOCK_DELTA:
                    # reflection 进步骤卡片；其余正文暂存为兜底，不进气泡
                    # （方案 B：回复气泡的唯一来源是 done.text，杜绝正文与 done 双发重复）
                    reflection, stream_text = _filter.feed(evt.delta)
                    if reflection:
                        yield {
                            "type": "event",
                            "event": {"type": "reflection", "data": reflection, "timestamp": 0},
                        }
                    if stream_text:
                        _trailing_text.append(stream_text)

                elif evt.type == EventType.TOOL_CALL_START:
                    # 工具调用前收尾：解析残余缓冲（未闭合的 JSON / 残留文本），重置过滤器
                    reflection, remaining = _filter.flush()
                    if reflection:
                        yield {
                            "type": "event",
                            "event": {"type": "reflection", "data": reflection, "timestamp": 0},
                        }
                    if remaining:
                        _trailing_text.append(remaining)

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
                    if evt.tool_call_name == "done":
                        # done 激活：其 text 参数将逐 token 流式进气泡（方案 B 唯一回复来源）
                        _done_active = True
                        _done_args = ""
                        _done_emitted = 0
                    elif evt.tool_call_name != "done":
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
                        # done 激活：从累积参数中增量提取 text 字段，只发新增部分（真流式打字机）
                        if _done_active and tc["name"] == "done":
                            _done_args = tc["args_buf"]
                            full = _extract_done_text(_done_args)
                            if len(full) > _done_emitted:
                                yield {"type": "stream", "content": full[_done_emitted:]}
                                _done_emitted = len(full)
                                if full:
                                    _done_emitted_any = True

                elif evt.type == EventType.TOOL_RESULT_TEXT_DELTA:
                    tc = _tool_calls.get(evt.tool_call_id)
                    if tc:
                        tc["result_buf"] += evt.delta

                elif evt.type == EventType.TOOL_RESULT_END:
                    tc = _tool_calls.get(evt.tool_call_id)
                    is_done = tc is not None and tc["name"] == "done"
                    if is_done:
                        # done 的 text 已在 TOOL_CALL_DELTA 阶段逐 token 流式发完，这里不再二次发送
                        _done_active = False
                        # 兜底：delta 阶段未产出任何文本（模型未填 text 或字段顺序异常），
                        # 用完整 args 重新解析补发一次，保证最终回复不丢
                        if not _done_emitted_any:
                            try:
                                parsed_args = json.loads(tc["args_buf"]) if tc["args_buf"] else {}
                            except (json.JSONDecodeError, TypeError):
                                parsed_args = {}
                            text_val = parsed_args.get("text") if isinstance(parsed_args, dict) else None
                            if text_val:
                                yield {"type": "stream", "content": text_val}
                                _done_emitted_any = True
                    elif tc:
                        try:
                            parsed_args = json.loads(tc["args_buf"]) if tc["args_buf"] else {}
                        except (json.JSONDecodeError, TypeError):
                            parsed_args = tc["args_buf"]
                        status = "done" if evt.state == ToolResultState.SUCCESS else "error"
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

            # 流式结束收尾：解析残余缓冲（未闭合的 JSON / 残留文本），重置过滤器
            reflection, remaining = _filter.flush()
            if reflection:
                yield {
                    "type": "event",
                    "event": {"type": "reflection", "data": reflection, "timestamp": 0},
                }
            if remaining:
                _trailing_text.append(remaining)

            # 兜底：done 全程未产出文本（模型未调用 done，或 done 无 text），
            # 把暂存的中间正文作为回复发出，避免气泡为空
            if not _done_emitted_any and _trailing_text:
                fallback = "".join(_trailing_text).strip()
                if fallback:
                    yield {"type": "stream", "content": fallback}

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
            # 兜底：done 尚未产出任何文本时，把暂存的中间正文作为回复发出，避免气泡为空
            if not _done_emitted_any and _trailing_text:
                fallback = "".join(_trailing_text).strip()
                if fallback:
                    try:
                        yield {"type": "stream", "content": fallback}
                    except Exception:
                        pass
            yield {
                "type": "event",
                "event": {"type": "activity_status", "data": {"status": "error"}},
            }
            yield {"type": "error", "message": f"Agent error: {e}"}
        finally:
            self._busy = False
