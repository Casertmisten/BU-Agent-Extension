# browser/tools.py
"""agentscope v2 Toolkit 的浏览器工具函数。

工厂模式：create_browser_tools() 返回一个异步函数字典，
每个函数通过闭包捕获 BrowserConnection 实例。
使用 Toolkit.register_tool_function() 注册。
"""

import json
from agentscope.tool import ToolResponse
from agentscope.message import TextBlock, UserMsg
from agentscope.message._block import DataBlock, Base64Source
from browser.connection import BrowserConnection
from logger import get_logger

log = get_logger("tools")


class _CompatToolResponse(ToolResponse):
    """ToolResponse 子类，添加 output 属性以简化文本输出。

    agentscope 的 ToolResponse 使用 content=[TextBlock(...)] 存储结果，
    本子类提供 output 快捷方式：构造时传入 output 字符串自动转为 TextBlock，
    读取 .output 时自动从 content 中提取文本。
    """

    def __init__(self, output: str = "", **kwargs):
        if "content" not in kwargs and output:
            kwargs["content"] = [TextBlock(type="text", text=output)]
        super().__init__(**kwargs)

    @property
    def output(self) -> str:
        texts = [b.text for b in self.content if isinstance(b, TextBlock)]
        return "".join(texts)


def create_browser_tools(
    conn: BrowserConnection,
    vlm_model,
    viewport_info: dict,
) -> dict[str, callable]:
    """创建绑定到指定连接的所有浏览器工具函数。"""

    # --- DOM 感知工具 ---

    async def parse_dom() -> _CompatToolResponse:
        """解析当前页面 DOM，返回可交互元素列表。"""
        result = await conn.send_action({"action": "parse_dom"})
        elements = result.get("data", {}).get("elements", [])
        return _CompatToolResponse(output=json.dumps(elements, ensure_ascii=False))

    async def get_element_info(target_id: str) -> _CompatToolResponse:
        """获取指定 DOM 元素的详细信息。"""
        result = await conn.send_action({"action": "get_element_info", "target_id": target_id})
        info = result.get("data", {})
        return _CompatToolResponse(output=json.dumps(info, ensure_ascii=False))

    # --- 操作执行工具 ---

    async def click_element(target_id: str) -> _CompatToolResponse:
        """通过 backend-id 点击元素。"""
        result = await conn.send_action({"action": "click", "target_id": target_id})
        return _CompatToolResponse(output=f"Click {target_id}: {result.get('status', 'unknown')}")

    async def input_text(target_id: str, text: str, clear_first: bool = True) -> _CompatToolResponse:
        """向输入元素输入文本。"""
        result = await conn.send_action({
            "action": "input_text",
            "target_id": target_id,
            "text": text,
            "clear_first": clear_first,
        })
        return _CompatToolResponse(output=f"Input to {target_id}: {result.get('status', 'unknown')}")

    async def scroll_page(direction: str = "down", pixels: int = 300) -> _CompatToolResponse:
        """滚动页面。"""
        result = await conn.send_action({
            "action": "scroll",
            "direction": direction,
            "pixels": pixels,
        })
        return _CompatToolResponse(output=f"Scroll {direction} {pixels}px: {result.get('status', 'unknown')}")

    async def navigate(url: str) -> _CompatToolResponse:
        """导航到指定 URL 并等待页面加载完成。"""
        result = await conn.send_action({"action": "navigate", "url": url})
        return _CompatToolResponse(output=f"Navigate to {url}: {result.get('status', 'unknown')}")

    async def wait(seconds: float = 2) -> _CompatToolResponse:
        """等待指定秒数。"""
        result = await conn.send_action({"action": "wait", "seconds": seconds})
        return _CompatToolResponse(output=f"Waited {seconds}s: {result.get('status', 'unknown')}")

    # --- 截图感知工具 ---

    async def screenshot_analyze() -> _CompatToolResponse:
        """截图并通过 VLM 模型分析。"""
        log.info("Taking screenshot for VLM analysis")
        result = await conn.send_action({"action": "screenshot"})
        image_base64 = result.get("data", {}).get("image", "")
        log.debug("Screenshot received, base64 length: %d", len(image_base64))

        vlm_msg = UserMsg(
            name="system",
            content=[
                DataBlock(source=Base64Source(
                    type="base64",
                    data=image_base64,
                    media_type="image/png",
                )),
                TextBlock(type="text", text="描述当前页面的状态、布局和所有可交互元素。包括按钮、输入框、链接等，标注它们的大致位置。"),
            ],
        )
        response = await vlm_model(vlm_msg)
        log.info("VLM analysis complete")
        return _CompatToolResponse(output=response.content)

    # --- CDP 降级工具 ---

    async def cdp_click(x: float, y: float) -> _CompatToolResponse:
        """通过 CDP 在绝对坐标处点击，自动根据 DPR 转换坐标。"""
        dpr = viewport_info.get("dpr", 1.0)
        css_x = x / dpr
        css_y = y / dpr
        result = await conn.send_action({"action": "cdp_click", "x": css_x, "y": css_y})
        return _CompatToolResponse(output=f"CDP click ({css_x:.0f}, {css_y:.0f}): {result.get('status', 'unknown')}")

    async def done(success: bool, text: str) -> _CompatToolResponse:
        """标记任务完成并返回结果给用户。"""
        return _CompatToolResponse(
            output=json.dumps({"done": True, "success": success, "text": text})
        )

    async def extract_content(target_id: str = "") -> _CompatToolResponse:
        """从当前页面或指定元素提取文本内容。"""
        result = await conn.send_action({"action": "extract_content", "target_id": target_id})
        return _CompatToolResponse(output=json.dumps(result.get("data", {}), ensure_ascii=False))

    async def go_back() -> _CompatToolResponse:
        """浏览器后退。"""
        result = await conn.send_action({"action": "go_back"})
        return _CompatToolResponse(output=f"Go back: {result.get('status', 'unknown')}")

    async def scroll_element(target_id: str, direction: str = "down", pixels: int = 300) -> _CompatToolResponse:
        """滚动指定可滚动元素。"""
        result = await conn.send_action({
            "action": "scroll_element",
            "target_id": target_id,
            "direction": direction,
            "pixels": pixels,
        })
        return _CompatToolResponse(output=f"Scroll element {target_id}: {result.get('status', 'unknown')}")

    return {
        "parse_dom": parse_dom,
        "get_element_info": get_element_info,
        "click_element": click_element,
        "input_text": input_text,
        "scroll_page": scroll_page,
        "scroll_element": scroll_element,
        "navigate": navigate,
        "go_back": go_back,
        "extract_content": extract_content,
        "wait": wait,
        "screenshot_analyze": screenshot_analyze,
        "cdp_click": cdp_click,
        "done": done,
    }
