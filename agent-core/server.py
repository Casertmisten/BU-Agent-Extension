# server.py
"""Browser Use Agent 的 WebSocket 服务器入口。"""

import asyncio
import json
import time

import websockets
from agentscope.agent import Agent
from agentscope.tool import Toolkit, FunctionTool
from agentscope.message import UserMsg
from agentscope.event import EventType
from agentscope.model import DashScopeChatModel, OpenAIChatModel
from agentscope.credential import DashScopeCredential, OpenAICredential

from browser.connection import BrowserConnection
from browser.protocol import validate_message
from browser.tools import create_browser_tools
from config_loader import load_config
from logger import get_logger, setup_logging
from agentscope.permission import PermissionContext, PermissionMode
from agentscope.state import AgentState

log = get_logger("server")


SYSTEM_PROMPT = """你是一个浏览器自动化 Agent。你通过可用工具控制网页浏览器。

工作流程：
1. 使用 parse_dom 了解页面结构，找到可交互元素。
2. 使用 click_element、input_text、scroll_page 通过 backend-id 操作元素。
3. 如果 DOM 解析失败或需要视觉上下文，使用 screenshot_analyze。
4. 当 DOM 交互失败时作为最后手段使用 cdp_click（截图分析给出坐标后）。
5. 使用 navigate 跳转 URL，wait 等待页面加载。

降级策略：
- 主方案：parse_dom → click_element / input_text（通过 backend-id）
- 备选：screenshot_analyze → cdp_click（通过 VLM 给出的坐标）
- 始终优先尝试 DOM 方式。仅在找不到元素时使用截图/CDP。

清晰地报告你的进展。任务完成时明确说明。"""


# ---------------------------------------------------------------------------
# 全局共享状态：一个浏览器只有一个 Agent 实例
# ---------------------------------------------------------------------------
class _ServerState:
    """跨 WebSocket 连接共享的 Agent 状态。

    Chrome 扩展可能因心跳超时、页面刷新等原因重连。
    每次重连会创建新的 WebSocket，但 Agent 和 conn 必须保持一致，
    否则工具发送的 action 结果会路由到错误的 conn 上。
    """

    def __init__(self):
        self.conn: BrowserConnection = BrowserConnection()
        self.agent: Agent | None = None
        self.viewport_info: dict = {}
        self.agent_busy = False
        self._current_ws = None  # 当前活跃的 WebSocket

    def init_agent(self, config: dict):
        """首次创建 Agent（只执行一次）。"""
        if self.agent is not None:
            return

        llm_model = _create_model(config["llm"])
        vlm_model = _create_model(config["vlm"])

        tool_functions = create_browser_tools(
            self.conn, vlm_model, self.viewport_info,
        )
        tool_objects = [FunctionTool(fn) for fn in tool_functions.values()]
        toolkit = Toolkit(tools=tool_objects)

        state = AgentState(
            permission_context=PermissionContext(mode=PermissionMode.BYPASS),
        )

        self.agent = Agent(
            name="browser_agent",
            model=llm_model,
            toolkit=toolkit,
            state=state,
            system_prompt=SYSTEM_PROMPT,
        )
        log.info("Created browser_agent with 9 tools (BYPASS mode)")

    def attach_ws(self, ws):
        """Chrome 扩展重连时，更新 conn 的 WebSocket 引用。"""
        old_ws = self._current_ws
        self._current_ws = ws
        self.conn.set_ws(ws)
        if old_ws is not None:
            log.info("WebSocket reconnected, updated conn reference")
        else:
            log.info("WebSocket attached to conn")


_state = _ServerState()


def _create_model(config: dict):
    """根据配置字典创建 agentscope 模型实例。"""
    provider = config["provider"]
    model_name = config["model"]
    api_key = config["api_key"]

    if provider == "openai":
        log.info("Loading model: %s", model_name)
        return OpenAIChatModel(
            credential=OpenAICredential(api_key=api_key),
            model=model_name,
        )
    elif provider == "dashscope":
        log.info("Loading model: %s", model_name)
        return DashScopeChatModel(
            credential=DashScopeCredential(api_key=api_key),
            model=model_name,
        )
    else:
        raise ValueError(
            f"Unsupported provider: {provider}. "
            f"Add support in server.py:_create_model(). Supported: openai, dashscope"
        )


async def handle_client(websocket, config: dict):
    """处理单个 WebSocket 客户端（Chrome 扩展）连接。

    核心设计：conn 和 agent 是全局共享的。
    Chrome 扩展重连时只更新 WebSocket 引用，不重建 Agent。
    """
    _state.init_agent(config)
    _state.attach_ws(websocket)

    async def run_agent(text: str):
        """运行 Agent 并将结果流式推送回客户端。"""
        ws = _state._current_ws  # 快照当前 ws，防止重连期间发送到旧的
        if _state.agent_busy:
            log.warning("Agent busy, rejecting message: %.50s", text)
            await ws.send(json.dumps({"type": "stream", "content": "[BUSY] Agent 正在工作中..."}))
            return
        _state.agent_busy = True
        log.info("Agent request: %.100s", text)
        try:
            event_count = 0
            async for evt in _state.agent.reply_stream(
                [UserMsg(name="user", content=text)]
            ):
                event_count += 1
                log.debug("Stream event #%d: type=%s", event_count, evt.type)
                if evt.type == EventType.TEXT_BLOCK_DELTA:
                    await _state._current_ws.send(
                        json.dumps({"type": "stream", "content": evt.delta})
                    )
            log.info("Stream ended, total events: %d", event_count)
            await _state._current_ws.send(
                json.dumps({"type": "stream", "content": "[DONE]"})
            )
            log.info("Agent completed successfully")
        except Exception as e:
            log.error("Agent error: %s", e, exc_info=True)
            try:
                await _state._current_ws.send(
                    json.dumps({"type": "error", "message": f"Agent error: {e}"})
                )
            except Exception:
                pass
        finally:
            _state.agent_busy = False

    try:
        async for raw_message in websocket:
            try:
                msg = json.loads(raw_message)
                validate_message(msg)
            except (json.JSONDecodeError, ValueError) as e:
                log.warning("Invalid message from client: %s", e)
                await websocket.send(json.dumps({"type": "error", "message": str(e)}))
                continue

            msg_type = msg["type"]

            if msg_type == "heartbeat":
                await websocket.send(json.dumps({"type": "heartbeat", "ts": time.time()}))

            elif msg_type == "result":
                _state.conn.handle_result(msg)

            elif msg_type == "page_ready":
                _state.viewport_info.update(msg.get("viewport", {}))
                log.debug("Page ready, viewport: %s", _state.viewport_info)

            elif msg_type == "user_message":
                log.info("User message received")
                asyncio.create_task(run_agent(msg.get("content", "")))

    except websockets.ConnectionClosed:
        log.info("Client disconnected")


async def main():
    """启动 WebSocket 服务器。"""
    config = load_config()
    setup_logging(config)

    host = config.get("server", {}).get("host", "localhost")
    port = config.get("server", {}).get("port", 8765)

    log.info("Starting Browser Use Agent server on ws://%s:%d", host, port)

    async with websockets.serve(
        lambda ws: handle_client(ws, config),
        host,
        port,
    ):
        await asyncio.Future()  # 永久运行


if __name__ == "__main__":
    asyncio.run(main())
