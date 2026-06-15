# browser/tools.py
"""浏览器自动化工具集（基于 agentscope ToolBase）。

每个工具都是 ToolBase 的子类，以类属性声明 name / description /
input_schema / 语义标记（is_read_only 等），在 __call__ 中实现逻辑并返回
ToolChunk。依赖（BrowserConnection / VLM 模型 / viewport 信息）通过构造
函数注入，避免闭包捕获带来的耦合。

create_browser_tools() 作为工厂，实例化所有工具并返回 list[ToolBase]。
"""

import json

from agentscope.tool import ToolBase
from agentscope.tool._response import ToolChunk
from agentscope.permission import (
    PermissionContext,
    PermissionDecision,
    PermissionBehavior,
)
from agentscope.message import (
    TextBlock,
    UserMsg,
    DataBlock,
    Base64Source,
    ToolResultState,
)

from browser.connection import BrowserConnection
from logger import get_logger

log = get_logger("tools")


# ---------------------------------------------------------------------------
# 工具基类：注入 BrowserConnection，统一只读/写权限策略
# ---------------------------------------------------------------------------


class _BrowserToolBase(ToolBase):
    """浏览器工具公共基类。

    子类只需声明 name/description/input_schema 并实现 __call__。
    权限策略按 is_read_only 自动派发：只读工具直接 ALLOW，有副作用工具
    PASSTHROUGH 给权限引擎按规则裁决（BYPASS 模式下会放行）。
    """

    def __init__(self, conn: BrowserConnection) -> None:
        self._conn = conn

    async def check_permissions(
        self,
        tool_input: dict,
        context: PermissionContext,
    ) -> PermissionDecision:
        if self.is_read_only:
            return PermissionDecision(
                behavior=PermissionBehavior.ALLOW,
                message=f"{self.name} 为只读操作。",
            )
        return PermissionDecision(
            behavior=PermissionBehavior.PASSTHROUGH,
            message=f"{self.name} 有副作用，交由权限引擎裁决。",
        )

    # 小工具：把动作结果包装成 ToolChunk 文本
    def _text(self, text: str, *, error: bool = False) -> ToolChunk:
        return ToolChunk(
            content=[TextBlock(text=text)],
            state=ToolResultState.ERROR if error else ToolResultState.RUNNING,
            is_last=True,
        )

    def _json(self, obj) -> ToolChunk:
        return self._text(json.dumps(obj, ensure_ascii=False))


# ---------------------------------------------------------------------------
# DOM 感知工具（只读）
# ---------------------------------------------------------------------------


class ParsePage(_BrowserToolBase):
    """解析页面结构。

    按 dom_strategy 决定后端：
    - "ax"（默认）：发 parse_page，返回无障碍树语义结构。
    - "flat"：发 parse_dom，返回旧版扁平元素列表。
    对外 name 始终为 parse_page，切换对 LLM 透明。
    """

    name = "parse_page"
    description = (
        "解析当前页面结构，返回基于无障碍树的语义化嵌套 JSON。"
        "可交互元素（按钮/链接/输入框等）带 agent-xx 标识，"
        "可供 click_element/input_text 等工具引用。"
    )
    input_schema = {
        "type": "object",
        "properties": {},
        "required": [],
    }
    is_read_only = True
    is_concurrency_safe = True

    def __init__(self, conn: BrowserConnection, dom_strategy: str = "ax") -> None:
        super().__init__(conn)
        self._strategy = "ax" if dom_strategy == "ax" else "flat"

    async def __call__(self) -> ToolChunk:
        action = "parse_page" if self._strategy == "ax" else "parse_dom"
        result = await self._conn.send_action({"action": action})
        data = result.get("data", {})
        # ax 返回 {tree:{...}}，flat 返回 {elements:[...]}
        payload = data.get("tree", data.get("elements", []))
        return self._json(payload)


class GetElementInfo(_BrowserToolBase):
    """获取指定 DOM 元素的详细信息。"""

    name = "get_element_info"
    description = "获取指定 DOM 元素的详细信息。"
    input_schema = {
        "type": "object",
        "properties": {
            "target_id": {
                "type": "string",
                "description": "目标元素的 backend id。",
            },
        },
        "required": ["target_id"],
    }
    is_read_only = True
    is_concurrency_safe = True

    async def __call__(self, target_id: str) -> ToolChunk:
        result = await self._conn.send_action(
            {"action": "get_element_info", "target_id": target_id}
        )
        return self._json(result.get("data", {}))


class ExtractContent(_BrowserToolBase):
    """从当前页面或指定元素提取文本内容。"""

    name = "extract_content"
    description = "从当前页面或指定元素提取文本内容。"
    input_schema = {
        "type": "object",
        "properties": {
            "target_id": {
                "type": "string",
                "description": "目标元素 backend id，为空则提取整页。",
            },
        },
        "required": [],
    }
    is_read_only = True
    is_concurrency_safe = True

    async def __call__(self, target_id: str = "") -> ToolChunk:
        result = await self._conn.send_action(
            {"action": "extract_content", "target_id": target_id}
        )
        return self._json(result.get("data", {}))


# ---------------------------------------------------------------------------
# 操作执行工具（有副作用）
# ---------------------------------------------------------------------------


class ClickElement(_BrowserToolBase):
    """通过 backend-id 点击元素。"""

    name = "click_element"
    description = "通过 backend-id 点击元素。"
    input_schema = {
        "type": "object",
        "properties": {
            "target_id": {
                "type": "string",
                "description": "目标元素的 backend id。",
            },
        },
        "required": ["target_id"],
    }
    is_read_only = False
    is_concurrency_safe = False

    async def __call__(self, target_id: str) -> ToolChunk:
        result = await self._conn.send_action(
            {"action": "click", "target_id": target_id}
        )
        return self._text(
            f"Click {target_id}: {result.get('status', 'unknown')}"
        )


class InputText(_BrowserToolBase):
    """向输入元素输入文本。"""

    name = "input_text"
    description = "向输入元素输入文本。"
    input_schema = {
        "type": "object",
        "properties": {
            "target_id": {
                "type": "string",
                "description": "目标输入元素的 backend id。",
            },
            "text": {
                "type": "string",
                "description": "要输入的文本。",
            },
            "clear_first": {
                "type": "boolean",
                "description": "是否先清空原内容，默认 true。",
                "default": True,
            },
        },
        "required": ["target_id", "text"],
    }
    is_read_only = False
    is_concurrency_safe = False

    async def __call__(
        self, target_id: str, text: str, clear_first: bool = True
    ) -> ToolChunk:
        result = await self._conn.send_action(
            {
                "action": "input_text",
                "target_id": target_id,
                "text": text,
                "clear_first": clear_first,
            }
        )
        return self._text(
            f"Input to {target_id}: {result.get('status', 'unknown')}"
        )


class ScrollPage(_BrowserToolBase):
    """滚动页面。"""

    name = "scroll_page"
    description = "滚动页面。"
    input_schema = {
        "type": "object",
        "properties": {
            "direction": {
                "type": "string",
                "description": "滚动方向：up/down。",
                "default": "down",
            },
            "pixels": {
                "type": "integer",
                "description": "滚动像素数。",
                "default": 300,
            },
        },
        "required": [],
    }
    is_read_only = False
    is_concurrency_safe = False

    async def __call__(
        self, direction: str = "down", pixels: int = 300
    ) -> ToolChunk:
        result = await self._conn.send_action(
            {"action": "scroll", "direction": direction, "pixels": pixels}
        )
        return self._text(
            f"Scroll {direction} {pixels}px: {result.get('status', 'unknown')}"
        )


class ScrollElement(_BrowserToolBase):
    """滚动指定可滚动元素。"""

    name = "scroll_element"
    description = "滚动指定可滚动元素。"
    input_schema = {
        "type": "object",
        "properties": {
            "target_id": {
                "type": "string",
                "description": "目标可滚动元素的 backend id。",
            },
            "direction": {
                "type": "string",
                "description": "滚动方向：up/down。",
                "default": "down",
            },
            "pixels": {
                "type": "integer",
                "description": "滚动像素数。",
                "default": 300,
            },
        },
        "required": ["target_id"],
    }
    is_read_only = False
    is_concurrency_safe = False

    async def __call__(
        self,
        target_id: str,
        direction: str = "down",
        pixels: int = 300,
    ) -> ToolChunk:
        result = await self._conn.send_action(
            {
                "action": "scroll_element",
                "target_id": target_id,
                "direction": direction,
                "pixels": pixels,
            }
        )
        return self._text(
            f"Scroll element {target_id}: {result.get('status', 'unknown')}"
        )


class Navigate(_BrowserToolBase):
    """导航到指定 URL 并等待页面加载完成。"""

    name = "navigate"
    description = "导航到指定 URL 并等待页面加载完成。"
    input_schema = {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "目标 URL。"},
        },
        "required": ["url"],
    }
    is_read_only = False
    is_concurrency_safe = False

    async def __call__(self, url: str) -> ToolChunk:
        result = await self._conn.send_action({"action": "navigate", "url": url})
        return self._text(
            f"Navigate to {url}: {result.get('status', 'unknown')}"
        )


class GoBack(_BrowserToolBase):
    """浏览器后退。"""

    name = "go_back"
    description = "浏览器后退。"
    input_schema = {
        "type": "object",
        "properties": {},
        "required": [],
    }
    is_read_only = False
    is_concurrency_safe = False

    async def __call__(self) -> ToolChunk:
        result = await self._conn.send_action({"action": "go_back"})
        return self._text(
            f"Go back: {result.get('status', 'unknown')}"
        )


class Wait(_BrowserToolBase):
    """等待指定秒数。"""

    name = "wait"
    description = "等待指定秒数。"
    input_schema = {
        "type": "object",
        "properties": {
            "seconds": {
                "type": "number",
                "description": "等待秒数。",
                "default": 2,
            },
        },
        "required": [],
    }
    is_read_only = True  # 等待不改变页面状态，视为只读
    is_concurrency_safe = True

    async def __call__(self, seconds: float = 2) -> ToolChunk:
        result = await self._conn.send_action({"action": "wait", "seconds": seconds})
        return self._text(
            f"Waited {seconds}s: {result.get('status', 'unknown')}"
        )


# ---------------------------------------------------------------------------
# 截图感知工具（VLM 分析，只读）
# ---------------------------------------------------------------------------


class ScreenshotAnalyze(_BrowserToolBase):
    """截图并通过 VLM 模型分析页面状态。"""

    name = "screenshot_analyze"
    description = "截图并通过 VLM 模型分析当前页面状态、布局和可交互元素。"
    input_schema = {
        "type": "object",
        "properties": {},
        "required": [],
    }
    is_read_only = True
    is_concurrency_safe = True

    def __init__(
        self,
        conn: BrowserConnection,
        vlm_model,
    ) -> None:
        super().__init__(conn)
        self._vlm = vlm_model

    async def __call__(self) -> ToolChunk:
        log.info("Taking screenshot for VLM analysis")
        result = await self._conn.send_action({"action": "screenshot"})
        image_base64 = result.get("data", {}).get("image", "")
        log.debug("Screenshot received, base64 length: %d", len(image_base64))

        vlm_msg = UserMsg(
            name="system",
            content=[
                DataBlock(
                    source=Base64Source(
                        type="base64",
                        data=image_base64,
                        media_type="image/jpeg",
                    )
                ),
                TextBlock(
                    type="text",
                    text="描述当前页面的状态、布局和所有可交互元素。包括按钮、输入框、链接等，标注它们的大致位置。",
                ),
            ],
        )
        # 模型 __call__ 要求 messages 为 list[Msg]，传单个 Msg 会抛
        # "Input must be a list of Msg objects."
        # 且默认 stream=True，返回 async generator(流式 ChatResponse)，需迭代累积文本
        response = await self._vlm([vlm_msg])
        parts = []
        async for chunk in response:
            for block in chunk.content:
                if isinstance(block, TextBlock):
                    parts.append(block.text)
        log.info("VLM analysis complete")
        return self._text("".join(parts))


# ---------------------------------------------------------------------------
# CDP 降级工具（坐标点击，有副作用）
# ---------------------------------------------------------------------------


class CdpClick(_BrowserToolBase):
    """通过 CDP 在绝对坐标处点击，自动根据 DPR 转换坐标。"""

    name = "cdp_click"
    description = "通过 CDP 在绝对坐标处点击，自动根据 DPR 转换坐标。"
    input_schema = {
        "type": "object",
        "properties": {
            "x": {"type": "number", "description": "横坐标（设备像素，内部按 DPR 换算）。"},
            "y": {"type": "number", "description": "纵坐标（设备像素，内部按 DPR 换算）。"},
        },
        "required": ["x", "y"],
    }
    is_read_only = False
    is_concurrency_safe = False

    def __init__(
        self,
        conn: BrowserConnection,
        viewport_info: dict,
    ) -> None:
        super().__init__(conn)
        self._viewport_info = viewport_info

    async def __call__(self, x: float, y: float) -> ToolChunk:
        dpr = self._viewport_info.get("dpr", 1.0)
        css_x = x / dpr
        css_y = y / dpr
        result = await self._conn.send_action(
            {"action": "cdp_click", "x": css_x, "y": css_y}
        )
        return self._text(
            f"CDP click ({css_x:.0f}, {css_y:.0f}): "
            f"{result.get('status', 'unknown')}"
        )


# ---------------------------------------------------------------------------
# 元工具：标记任务完成
# ---------------------------------------------------------------------------


class Done(ToolBase):
    """标记任务完成并返回结果给用户（元工具，无浏览器依赖）。"""

    name = "done"
    description = "标记任务完成并返回最终结果给用户。"
    input_schema = {
        "type": "object",
        "properties": {
            "success": {
                "type": "boolean",
                "description": "任务是否成功完成。",
            },
            "text": {
                "type": "string",
                "description": "给用户的最终汇报文本。",
            },
        },
        "required": ["success", "text"],
    }
    is_read_only = True
    is_concurrency_safe = True

    async def check_permissions(
        self,
        tool_input: dict,
        context: PermissionContext,
    ) -> PermissionDecision:
        return PermissionDecision(
            behavior=PermissionBehavior.ALLOW,
            message="done 为元工具，始终允许。",
        )

    async def __call__(self, success: bool, text: str) -> ToolChunk:
        return ToolChunk(
            content=[
                TextBlock(
                    text=json.dumps(
                        {"done": True, "success": success, "text": text},
                        ensure_ascii=False,
                    )
                )
            ],
            state=ToolResultState.RUNNING,
            is_last=True,
        )


# ---------------------------------------------------------------------------
# 工厂：实例化所有工具
# ---------------------------------------------------------------------------


def create_browser_tools(
    conn: BrowserConnection,
    vlm_model,
    viewport_info: dict,
    dom_strategy: str = "ax",
) -> list[ToolBase]:
    """创建绑定到指定连接的所有浏览器工具实例。

    Args:
        conn: 浏览器连接实例。
        vlm_model: VLM 模型实例（供截图分析工具使用）。
        viewport_info: 视口信息字典（供 CDP 坐标换算使用）。
        dom_strategy: DOM 解析策略，"ax" 或 "flat"，决定 ParsePage 后端。

    Returns:
        组装好的 ToolBase 实例列表，可直接喂给 agentscope Toolkit。
    """
    return [
        # 页面结构解析（ax 或 flat，由 dom_strategy 决定）
        ParsePage(conn, dom_strategy),
        # DOM 细节查询（只读）
        GetElementInfo(conn),
        ExtractContent(conn),
        # 操作执行（有副作用）
        ClickElement(conn),
        InputText(conn),
        ScrollPage(conn),
        ScrollElement(conn),
        Navigate(conn),
        GoBack(conn),
        Wait(conn),
        # 截图感知（只读，依赖 VLM）
        ScreenshotAnalyze(conn, vlm_model),
        # CDP 降级（有副作用，依赖 viewport_info）
        CdpClick(conn, viewport_info),
        # 元工具
        Done(),
    ]
