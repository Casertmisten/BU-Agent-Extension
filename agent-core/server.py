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

from browser.connection import BrowserConnection
from browser.protocol import validate_message
from browser.tools import create_browser_tools
from config_loader import load_config


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


def _create_model(config: dict):
    """根据配置字典创建 agentscope 模型实例。"""
    provider = config["provider"]
    model_name = config["model"]
    api_key = config["api_key"]

    if provider == "openai":
        from agentscope.model import OpenAIChatModel
        from agentscope.credential import OpenAICredential
        return OpenAIChatModel(
            credential=OpenAICredential(api_key=api_key),
            model=model_name,
        )
    elif provider == "dashscope":
        from agentscope.model import DashScopeChatModel
        from agentscope.credential import DashScopeCredential
        return DashScopeChatModel(
            credential=DashScopeCredential(api_key=api_key),
            model=model_name,
        )
    else:
        raise ValueError(
            f"Unsupported provider: {provider}. "
            f"Add support in server.py:_create_model(). Supported: openai, dashscope"
        )


def create_agent(conn: BrowserConnection, vlm_model, viewport_info: dict, llm_model) -> Agent:
    """创建注册了全部 9 个工具的浏览器自动化 Agent。"""
    tool_functions = create_browser_tools(conn, vlm_model, viewport_info)

    tool_objects = [FunctionTool(fn) for fn in tool_functions.values()]
    toolkit = Toolkit(tools=tool_objects)

    return Agent(
        name="browser_agent",
        model=llm_model,
        toolkit=toolkit,
        system_prompt=SYSTEM_PROMPT,
    )


async def handle_client(websocket, config: dict):
    """处理单个 WebSocket 客户端（Chrome 扩展）连接。"""
    conn = BrowserConnection()
    conn.set_ws(websocket)

    llm_model = _create_model(config["llm"])
    vlm_model = _create_model(config["vlm"])
    viewport_info = {}

    agent = create_agent(conn, vlm_model, viewport_info, llm_model)
    agent_busy = False

    async def run_agent(text: str):
        """运行 Agent 并将结果流式推送回客户端。"""
        nonlocal agent_busy
        if agent_busy:
            await websocket.send(json.dumps({"type": "stream", "content": "[BUSY] Agent 正在工作中..."}))
            return
        agent_busy = True
        try:
            async for evt in agent.reply_stream(UserMsg(name="user", content=text)):
                if evt.type == EventType.TEXT_BLOCK_DELTA:
                    await websocket.send(json.dumps({"type": "stream", "content": evt.delta}))
            await websocket.send(json.dumps({"type": "stream", "content": "[DONE]"}))
        except Exception as e:
            await websocket.send(json.dumps({"type": "error", "message": f"Agent error: {e}"}))
        finally:
            agent_busy = False

    try:
        async for raw_message in websocket:
            try:
                msg = json.loads(raw_message)
                validate_message(msg)
            except (json.JSONDecodeError, ValueError) as e:
                await websocket.send(json.dumps({"type": "error", "message": str(e)}))
                continue

            msg_type = msg["type"]

            if msg_type == "heartbeat":
                await websocket.send(json.dumps({"type": "heartbeat", "ts": time.time()}))

            elif msg_type == "result":
                conn.handle_result(msg)

            elif msg_type == "page_ready":
                viewport_info.update(msg.get("viewport", {}))

            elif msg_type == "user_message":
                asyncio.create_task(run_agent(msg.get("content", "")))

    except websockets.ConnectionClosed:
        pass


async def main():
    """启动 WebSocket 服务器。"""
    config = load_config()
    host = config.get("server", {}).get("host", "localhost")
    port = config.get("server", {}).get("port", 8765)

    print(f"Starting Browser Use Agent server on ws://{host}:{port}")

    async with websockets.serve(
        lambda ws: handle_client(ws, config),
        host,
        port,
    ):
        await asyncio.Future()  # 永久运行


if __name__ == "__main__":
    asyncio.run(main())
