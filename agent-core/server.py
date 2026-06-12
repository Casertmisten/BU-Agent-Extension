# server.py
"""WebSocket 服务器入口。

职责：启动 WS 服务、路由消息到 BrowserAgent。
Agent 相关逻辑全部在 agent/ 模块中。
"""

import asyncio
import json
import time
from dotenv import load_dotenv

load_dotenv()

import websockets

from agent import BrowserAgent
from browser.protocol import validate_message
from config_loader import load_config
from logger import get_logger, setup_logging

log = get_logger("server")

# 全局唯一的 Agent 实例
_agent: BrowserAgent | None = None


def _get_or_create_agent(config: dict) -> BrowserAgent:
    """获取或创建全局 BrowserAgent 实例（单例）。"""
    global _agent
    if _agent is None:
        _agent = BrowserAgent(config)
        _agent.init()
    return _agent


async def _run_agent_and_send(agent: BrowserAgent, text: str):
    """运行 Agent 并将流式结果推送到当前活跃的 WebSocket。

    使用 agent._current_ws 获取最新引用，确保重连后消息发到新 WS。
    """
    async for event in agent.run(text):
        ws = agent._current_ws
        if ws is None:
            break
        try:
            await ws.send(json.dumps(event))
        except Exception:
            pass


async def handle_client(websocket, config: dict):
    """处理 WebSocket 客户端（Chrome 扩展）连接。

    Chrome 扩展重连时只更新 WebSocket 引用，不重建 Agent。
    """
    agent = _get_or_create_agent(config)
    agent.attach_ws(websocket)

    # 重连时通知前端之前的状态已丢失
    if agent._busy:
        log.warning("重连时 Agent 仍在执行，前端可能需要刷新状态")

    try:
        async for raw_message in websocket:
            try:
                msg = json.loads(raw_message)
                validate_message(msg)
            except (json.JSONDecodeError, ValueError) as e:
                log.warning("无效消息: %s", e)
                await websocket.send(json.dumps({"type": "error", "message": str(e)}))
                continue

            msg_type = msg["type"]

            if msg_type == "heartbeat":
                await websocket.send(json.dumps({"type": "heartbeat", "ts": time.time()}))

            elif msg_type == "result":
                agent.conn.handle_result(msg)

            elif msg_type == "page_ready":
                agent.viewport_info.update(msg.get("viewport", {}))
                log.debug("页面就绪, viewport: %s", agent.viewport_info)

            elif msg_type == "user_message":
                log.info("收到用户消息")
                asyncio.create_task(
                    _run_agent_and_send(agent, msg.get("content", ""))
                )

    except websockets.ConnectionClosed:
        log.info("客户端断开连接，清理挂起的工具请求")
        agent.conn.disconnect()


async def main():
    """启动 WebSocket 服务器。"""
    config = load_config()
    setup_logging(config)

    host = config.get("server", {}).get("host", "localhost")
    port = config.get("server", {}).get("port", "8765")

    log.info("启动 Browser Use Agent 服务器 ws://%s:%s", host, port)

    async with websockets.serve(
        lambda ws: handle_client(ws, config),
        host,
        port,
    ):
        await asyncio.Future()  # 永久运行


if __name__ == "__main__":
    asyncio.run(main())
