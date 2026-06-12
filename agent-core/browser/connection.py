# browser/connection.py
"""BrowserConnection：向 Chrome 扩展发送工具指令并等待结果。"""

import asyncio
import json
from uuid import uuid4

from logger import get_logger

log = get_logger("connection")


class BrowserConnection:
    """追踪挂起的工具指令，将结果路由回等待的调用者。"""

    def __init__(self):
        self._ws = None
        self._pending: dict[str, asyncio.Future] = {}
        self.viewport_info: dict = {}

    def set_ws(self, ws):
        """设置活跃的 WebSocket 连接。"""
        self._ws = ws

    def disconnect(self):
        """WS 断开时清理所有挂起的 Future，防止永久阻塞。

        所有正在等待 send_action 结果的协程会收到 ConnectionError。
        """
        if not self._pending:
            return
        log.info("清理 %d 个挂起的工具请求", len(self._pending))
        for task_id, future in self._pending.items():
            if not future.done():
                future.set_exception(
                    ConnectionError(f"WebSocket 断开，task_id={task_id}")
                )
        self._pending.clear()
        self._ws = None

    async def send_action(self, action: dict) -> dict:
        """向 Chrome 扩展发送指令并等待结果。

        Args:
            action: 包含指令特定字段的字典，如 {"action": "click", "target_id": "agent-05"}。

        Returns:
            Chrome 扩展返回的结果消息字典。

        Raises:
            RuntimeError: WebSocket 未连接。
            ConnectionError: 等待期间 WebSocket 断开。
            Exception: Chrome 扩展报告错误。
        """
        if self._ws is None:
            raise RuntimeError("WebSocket not connected")

        task_id = uuid4().hex[:8]
        action["task_id"] = task_id
        action["type"] = "action"

        loop = asyncio.get_running_loop()
        future = loop.create_future()
        self._pending[task_id] = future

        log.debug("Sending action: %s (task_id=%s)", action.get("action"), task_id)
        await self._ws.send(json.dumps(action))

        result = await future
        log.debug("Action result: %s status=%s", action.get("action"), result.get("status"))
        return result

    def handle_result(self, msg: dict):
        """将结果消息路由到等待的 Future。"""
        task_id = msg.get("task_id")
        if task_id is None or task_id not in self._pending:
            log.warning("Unknown task_id in result: %s", task_id)
            return

        future = self._pending.pop(task_id)
        if msg.get("status") == "success":
            future.set_result(msg)
        else:
            log.error("Action failed: %s", msg.get("error", "Unknown error"))
            future.set_exception(Exception(msg.get("error", "Unknown error")))

    def update_viewport(self, viewport: dict):
        """从 page_ready 消息更新缓存的视口信息。"""
        self.viewport_info.update(viewport)
