# Browser Use Agent 设计文档

> 日期：2026-06-10
> 定位：个人工具/原型
> 框架：agentscope v2 (agentscope-ai)

## 1. 项目概述

一个浏览器自动化 Agent 系统，用户通过 Chrome Extension 的 SidePanel 输入任务指令，后端 Agent Core 基于多模态感知（DOM + 截图）自动操控网页，完成表单填写、数据采集、多步骤工作流等任务。

支持 **AI 模式**（Agent 自动操控网页）和 **人工模式**（用户手动操作）的切换，AI 模式下通过页面遮罩层防止用户误操作干扰 Agent 执行。

## 2. 系统架构

```
┌──────────────────────────────────────────────────────────┐
│                   Chrome Extension                        │
│  ┌────────────┐  ┌────────────────┐  ┌────────────────┐  │
│  │ SidePanel  │  │ background.js  │  │ Content Script │  │
│  │ (Chat UI)  │  │ (Service Worker│  │ (DOM 操作/     │  │
│  │ 模式切换   │  │  WS管理/截图   │  │  元素打标)     │  │
│  └─────┬──────┘  │ CDP坐标点击)  │  └───────┬────────┘  │
│        │chrome.  └───────┬────────┘         │chrome.     │
│        │runtime.         │WebSocket         │scripting   │
│        │sendMessage      │                  │            │
│        └────────┬────────┘                  │            │
└─────────────────┼───────────────────────────┼────────────┘
                  │ ws://localhost:8765        │
┌─────────────────┼───────────────────────────┼────────────┐
│           Agent Core (Python)                │            │
│        ┌────────┴────────┐                   │            │
│        │  WebSocket Server│◄─────────────────┘            │
│        └────────┬────────┘                               │
│  ┌─────────────┼──────────────┐                           │
│  │   Main Agent (agentscope)  │                           │
│  │   ┌────────┼──────────┐    │                           │
│  │   │ Toolkit (ToolBase)│    │                           │
│  │   │ ├ DOMParser       │    │  Content Script 执行      │
│  │   │ ├ GetElementInfo  │    │                           │
│  │   │ ├ ScreenshotAnalyze│   │  background.js 执行       │
│  │   │ ├ ClickElement    │    │  Content Script 执行      │
│  │   │ ├ InputText       │    │                           │
│  │   │ ├ ScrollPage      │    │                           │
│  │   │ ├ NavigateTo      │    │                           │
│  │   │ ├ Wait            │    │                           │
│  │   │ └ CDPClick        │    │  background.js+CDP 执行   │
│  │   └───────────────────┘    │                           │
│  └────────────────────────────┘                           │
│  Config: LLM/VLM 可配置切换                                │
└───────────────────────────────────────────────────────────┘
```

### 指令路由规则

不同工具的执行端不同，由 background.js 统一做路由分发：

| 工具 | 执行端 | 路径 |
|---|---|---|
| parse_dom / get_element_info / click / input_text / scroll | Content Script | background → chrome.scripting.executeScript → content.js |
| screenshot | background.js | background 直接调用 `chrome.tabs.captureVisibleTab` |
| navigate | background.js | background 调用 `chrome.tabs.update` |
| CDPClick | background.js | background 调用 `chrome.debugger` (CDP) |
| wait | background.js | background 监听 `chrome.tabs.onUpdated` + content script 握手 |

### 通信流

1. 用户在 SidePanel 输入任务指令
2. SidePanel 通过 `chrome.runtime.sendMessage` 发到 background.js
3. background.js（Service Worker）通过 WebSocket 发送到 Agent Core
4. Agent Core 的 Main Agent 推理后调用工具
5. 工具指令通过 WebSocket 下发到 background.js
6. background.js 根据指令类型路由：
   - **DOM 操作类** → `chrome.scripting.executeScript` 注入/调用 Content Script
   - **截图** → 直接调用 `chrome.tabs.captureVisibleTab`，返回 base64
   - **CDP 点击** → `chrome.debugger.attach` + `Input.dispatchMouseEvent`
   - **导航** → `chrome.tabs.update`，监听加载完成
7. 执行结果返回 Agent Core，Agent 决定下一步
8. 循环直到任务完成，流式推送 Agent 回复到 SidePanel

## 3. Chrome Extension 端

### 技术栈

Manifest V3 + SidePanel API + chrome.scripting + chrome.debugger

### 目录结构

```
chrome-extension/
├── manifest.json          # MV3，声明 side_panel、scripting、debugger、tabs 权限
├── background.js          # Service Worker：WS 连接、截图、CDP、路由分发
├── sidepanel/
│   ├── sidepanel.html     # 聊天 UI + 模式切换按钮
│   └── sidepanel.js       # 消息收发、状态展示、模式切换
├── content/
│   └── content.js         # 注入页面：DOM 操作、元素打标、遮罩层管理
└── libs/
    └── ws-client.js       # WebSocket 客户端封装（含心跳）
```

### manifest.json 关键权限

```json
{
  "permissions": [
    "sidePanel",
    "scripting",
    "tabs",
    "debugger",
    "alarms",
    "activeTab"
  ],
  "host_permissions": ["<all_urls>"],
  "background": { "service_worker": "background.js" },
  "side_panel": { "default_path": "sidepanel/sidepanel.html" }
}
```

### 关键设计决策

1. **WebSocket 放在 background.js（Service Worker）**：管理连接生命周期，sidepanel 关闭不断连。sidepanel 通过 `chrome.runtime.sendMessage` 与 background 通信。

2. **截图由 background.js 直接执行**：`chrome.tabs.captureVisibleTab` 是特权 API，只有 Service Worker 和 sidepanel 有权限调用。Content Script 无权调用。截图指令不走 Content Script，background.js 截取后将 base64 通过 WebSocket 直接返回 Agent Core。

3. **Content Script 职责**：
   - 执行 DOM 操作（点击、输入、滚动）
   - 解析 DOM 树，给可交互元素打标签（backend-id），返回简化列表
   - 管理 AI 模式的遮罩层（注入/移除 overlay）

4. **CDP 坐标点击由 background.js 执行**：通过 `chrome.debugger` 协议的 `Input.dispatchMouseEvent` 实现穿透沙箱的绝对坐标点击，用于截图降级模式。

### AI 模式 / 人工模式切换

SidePanel 提供模式切换按钮：

- **AI 模式**：Content Script 注入全屏半透明遮罩层（`pointer-events: auto`，`z-index: 999999`），拦截所有用户点击，防止干扰 Agent 操作
- **人工模式**：移除遮罩层，用户可正常操作网页；Agent 暂停执行，等待切换回 AI 模式

```javascript
// content.js 遮罩层管理
let overlay = null;

function enableOverlay() {
    if (overlay) return;
    overlay = document.createElement("div");
    overlay.id = "__agent_overlay__";
    overlay.style.cssText = `
        position: fixed; top: 0; left: 0;
        width: 100vw; height: 100vh;
        z-index: 999999;
        background: rgba(0, 0, 0, 0.15);
        pointer-events: auto;
    `;
    document.body.appendChild(overlay);
}

function disableOverlay() {
    overlay?.remove();
    overlay = null;
}
```

### 消息协议

```json
// 心跳（双向，每 30s）
{ "type": "heartbeat", "ts": 1718000000 }

// 指令下发
{ "type": "action", "action": "click", "target_id": "agent-05", "task_id": "xxx" }
{ "type": "action", "action": "cdp_click", "x": 320, "y": 480, "task_id": "xxx" }
{ "type": "action", "action": "input_text", "target_id": "agent-12", "text": "hello", "clear_first": true, "task_id": "xxx" }
{ "type": "action", "action": "screenshot", "task_id": "xxx" }
{ "type": "action", "action": "parse_dom", "task_id": "xxx" }
{ "type": "action", "action": "navigate", "url": "https://...", "task_id": "xxx" }
{ "type": "action", "action": "scroll", "direction": "down", "pixels": 300, "task_id": "xxx" }
{ "type": "action", "action": "wait", "seconds": 2, "task_id": "xxx" }

// 结果上报
{ "type": "result", "task_id": "xxx", "status": "success", "data": { ... } }
{ "type": "result", "task_id": "xxx", "status": "error", "error": "元素未找到" }

// 页面就绪通知（导航/刷新后，携带视口信息供 CDP 坐标换算）
{ "type": "page_ready", "url": "https://...", "tab_id": 123, "viewport": { "dpr": 2.0, "width": 1280, "height": 720 } }

// Agent 流式回复
{ "type": "stream", "content": "正在分析页面..." }

// 模式切换
{ "type": "mode_change", "mode": "ai" | "manual" }
```

### 心跳 + Alarms 双重保活机制

background.js（Service Worker）在浏览器长时间无操作时会被 Chrome 强制休眠。MV3 的休眠机制非常激进，即使 WebSocket 处于活跃状态，Chrome 仍可能在 5 分钟后强行杀掉 Service Worker。因此需要双重保活：

**1. WebSocket 心跳**（应用层）：
- Agent Core 和 background.js 每 30s 互发 heartbeat
- 超过 90s 未收到心跳视为断连，触发重连逻辑

**2. chrome.alarms 定时器**（系统层）：
- `chrome.alarms` 不受 Service Worker 生命周期限制，是 MV3 下最可靠的保活手段
- 每 1 分钟触发一次，唤醒 Service Worker

```javascript
// background.js 双重保活
chrome.alarms.create('keepAlive', { periodInMinutes: 1 });
chrome.alarms.onAlarm.addListener((alarm) => {
    if (alarm.name === 'keepAlive') {
        // 唤醒 Service Worker，检查 WebSocket 连接状态
        if (!wsClient || wsClient.readyState !== WebSocket.OPEN) {
            reconnectWebSocket();
        }
    }
});
```

manifest.json 需声明 `alarms` 权限。

## 4. Agent Core 后端

### 技术栈

Python + agentscope v2 + websockets（asyncio 原生）

### 目录结构

```
agent-core/
├── pyproject.toml              # uv 管理
├── config.yaml                 # LLM/VLM 配置
├── server.py                   # WebSocket 服务器入口
├── agent/
│   ├── __init__.py
│   ├── main_agent.py           # Main Agent（agentscope Agent 封装）
│   └── tools/
│       ├── __init__.py
│       ├── dom_parser.py       # DOMParser Tool（元素打标 + 简化返回）
│       ├── screenshot.py       # ScreenshotAnalyze Tool（截图 + VLM 分析）
│       ├── actions.py          # ClickElement / InputText / ScrollPage / NavigateTo / Wait
│       ├── cdp_click.py        # CDPClick Tool（坐标点击，CDP 降级）
│       └── tool_helpers.py     # BrowserTool 基类（WS 通信封装）
├── ws/
│   ├── __init__.py
│   ├── connection.py           # WebSocket 连接管理 + 心跳
│   └── protocol.py             # 消息协议定义（dataclass）
└── config/
    └── loader.py               # 读取 config.yaml，初始化 Credential
```

### 工具执行机制

工具执行不在 Python 端，而是下发到 Chrome Extension。`BrowserTool` 基类封装 WS 通信：

```python
# tool_helpers.py 核心逻辑
class BrowserTool(ToolBase):
    """所有浏览器工具的基类，封装 WS 通信"""
    ws_connection: WebSocket

    async def send_action(self, action: dict) -> dict:
        task_id = uuid4().hex[:8]
        action["task_id"] = task_id
        await self.ws_connection.send(json.dumps(action))
        return await self.wait_for_result(task_id)
```

### ScreenshotAnalyze 工具特殊处理

截图工具需要额外处理：background.js 返回 base64 图片后，Agent Core 调用 VLM 分析，将分析文本返回给 Agent：

```python
# screenshot.py 核心逻辑
class ScreenshotAnalyze(BrowserTool):
    vlm_model: ChatModelBase  # VLM 模型实例

    async def execute(self) -> str:
        # 1. 下发截图指令到 background.js
        result = await self.send_action({"action": "screenshot"})
        image_base64 = result["data"]["image"]

        # 2. 调用 VLM 分析截图
        analysis = await self.vlm_model.chat(
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_base64}"}},
                    {"type": "text", "text": "描述当前页面的状态和可交互元素"}
                ]
            }]
        )
        return analysis
```

### config.yaml

```yaml
llm:
  provider: openai          # openai / anthropic / dashscope / ollama
  model: gpt-4o
  api_key: ${OPENAI_API_KEY}

vlm:
  provider: openai          # 截图分析用的 VLM
  model: gpt-4o
  api_key: ${OPENAI_API_KEY}

server:
  host: localhost
  port: 8765
  heartbeat_interval: 30    # 心跳间隔（秒）
```

## 5. 工具详细设计

### 混合感知策略

DOM 为主 + 截图为辅。Agent 的 system prompt 内置降级逻辑，靠 LLM 推理决定何时切换。

### 元素打标机制（DOM 解析优化）

参考 WebArena / AutoGLM 做法，在 `parse_dom` 时 Content Script 给每个可交互元素动态注入 `backend-id`：

```javascript
// content.js 元素打标
let counter = 0;
function tagElements() {
    const interactable = document.querySelectorAll(
        'a, button, input, select, textarea, [role="button"], [onclick]'
    );
    // 移除旧标签
    document.querySelectorAll('[backend-id]').forEach(el => {
        el.removeAttribute('backend-id');
    });
    counter = 0;
    const elements = [];
    interactable.forEach(el => {
        const id = String(counter++).padStart(2, '0');
        el.setAttribute('backend-id', `agent-${id}`);
        elements.push({
            id: `agent-${id}`,
            tag: el.tagName.toLowerCase(),
            text: el.textContent?.trim().slice(0, 50) || '',
            type: el.type || '',
            placeholder: el.placeholder || '',
        });
    });
    return elements;
}
```

**收益**：
- 返回数据从完整 DOM 节点大幅简化为扁平文本列表
- Agent 决策后直接用 `backend-id`（如 `agent-05`）下发操作指令
- Content Script 通过 `document.querySelector('[backend-id="agent-05"]')` 精准定位，无需 xpath
- 减少 Token 消耗和 WebSocket 传输体积

### 工具清单

| 类别 | 工具 | 执行端 | 输入 | 输出 | 说明 |
|---|---|---|---|---|---|
| DOM 感知 | `parse_dom` | Content Script | 过滤规则（可选） | 简化元素列表 | 打标 + 返回 `{id, tag, text, type}` |
| DOM 感知 | `get_element_info` | Content Script | backend-id | 元素详情 | 属性、文本、可见性、rect |
| 截图感知 | `screenshot` | background.js | 无 | VLM 分析文本 | 截图 → VLM → 文本描述 |
| 操作执行 | `click` | Content Script | backend-id | 成功/失败 | 根据 backend-id 定位点击 |
| 操作执行 | `input_text` | Content Script | backend-id, text, clear_first | 成功/失败 | 输入文本 |
| 操作执行 | `scroll` | Content Script | direction, pixels | 成功/失败 | 上/下/左/右滚动 |
| 操作执行 | `navigate` | background.js | url | 成功/失败 | 导航 + 等待页面就绪 |
| 操作执行 | `wait` | background.js | seconds | 成功 | 等待页面加载/动画 |
| CDP 降级 | `cdp_click` | background.js (CDP) | x, y | 成功/失败 | CSS 像素坐标物理点击，穿透沙箱 |

### 降级策略

```
Agent 尝试操作
  ├─ DOM 解析成功 → 打标 → 用 backend-id 定位 → 执行操作
  ├─ 元素未找到   → 截图 → VLM 分析目标位置 → CDP 坐标点击（cdp_click）
  └─ 操作失败     → 截图 → VLM 判断页面状态 → 重新规划
```

CDP 点击通过 `chrome.debugger` 的 `Input.dispatchMouseEvent` 实现，能穿透跨域 iframe 和反爬机制。

### CDP 坐标换算

`Input.dispatchMouseEvent` 接收的 (x, y) 是 **CSS 像素**，相对于浏览器视口左上角。而 VLM 从截图获取的坐标是**图片像素**，两者存在换算关系：

```
CSS_x = image_x / devicePixelRatio
CSS_y = image_y / devicePixelRatio
```

**流程：**
1. 前端在 `page_ready` 和每次截图时上报 `window.devicePixelRatio`
2. VLM 分析截图返回目标坐标（图片像素）
3. Agent Core 的 `cdp_click` 工具根据 `devicePixelRatio` 换算为 CSS 像素后再下发

```json
// page_ready 时上报视口信息
{ "type": "page_ready", "url": "...", "tab_id": 123, "viewport": { "dpr": 2.0, "width": 1280, "height": 720 } }
```

```python
# cdp_click.py 核心逻辑
class CDPClick(BrowserTool):
    viewport_info: dict  # 包含 dpr

    async def execute(self, x: float, y: float) -> str:
        # VLM 返回的 x, y 是图片像素，换算为 CSS 像素
        dpr = self.viewport_info.get("dpr", 1.0)
        css_x = x / dpr
        css_y = y / dpr
        return await self.send_action({
            "action": "cdp_click",
            "x": css_x,
            "y": css_y,
        })
```

## 6. 页面导航状态管理

页面导航（navigate 或导致跳转的 click）会导致 Content Script 销毁重建，必须处理状态断裂：

### 就绪握手机制

1. Agent Core 下发 `navigate` 指令
2. background.js 调用 `chrome.tabs.update` 导航
3. background.js 监听 `chrome.tabs.onUpdated`，等待 `status === "complete"`
4. background.js 通过 `chrome.scripting.executeScript` 注入 Content Script
5. Content Script 加载完成后发送 `{ "type": "page_ready", "url": "...", "tab_id": 123 }`
6. Agent Core 收到 `page_ready` 后才允许下发下一个工具指令

```javascript
// background.js 导航就绪监听
async function navigateAndWait(url, tabId) {
    await chrome.tabs.update(tabId, { url });
    return new Promise((resolve) => {
        const listener = (updatedTabId, changeInfo) => {
            if (updatedTabId === tabId && changeInfo.status === "complete") {
                chrome.tabs.onUpdated.removeListener(listener);
                // 注入 content script 并等待握手
                injectContentScript(tabId).then(resolve);
            }
        };
        chrome.tabs.onUpdated.addListener(listener);
    });
}
```

### 跳转类 click 的处理

当 click 操作导致页面跳转时（如点击 `<a>` 链接），Content Script 会被销毁。background.js 检测到 tab URL 变化后，自动触发与 navigate 相同的就绪握手流程，并通过 `page_ready` 通知 Agent Core。

## 7. 错误处理

| 场景 | 策略 |
|---|---|
| WebSocket 断连 | Extension 端自动重连（指数退避），Agent Core 维护会话状态 |
| Service Worker 休眠 | 心跳 + chrome.alarms 双重保活；alarms 每 1min 唤醒并检查连接 |
| DOM 元素未找到 | Agent 自动降级到截图 + CDP 点击模式，最多重试 3 次 |
| 页面导航后 Content Script 断裂 | page_ready 握手机制，超时 10s 后报错让 Agent 重试 |
| 页面加载超时 | `wait` 工具 + `chrome.tabs.onUpdated` 监听 |
| LLM API 失败 | agentscope 的 `ModelConfig(max_retries=2, fallback_model=...)` |
| CDP attach 失败 | 降级为 Content Script 的 `document.elementFromPoint` 点击 |
| CDP 坐标偏差 | 前端上报 devicePixelRatio，cdp_click 自动换算图片像素 → CSS 像素 |
| 工具执行异常 | 返回错误信息给 Agent，让 LLM 决定下一步 |

## 8. 测试策略

- **单元测试：** 工具类逻辑（DOM 解析、消息协议序列化、元素打标）
- **集成测试：** 用 mock WebSocket 验证 Agent → 工具 → 返回结果的完整链路
- **手工验收：** 实际在 SidePanel 输入任务，观察端到端执行

暂不做 E2E 自动化测试。

## 9. 演进路径（单体 → 多 Agent Pipeline）

### 阶段 1（当前 MVP）：Main Agent + Toolkit

单个 Agent 通过 tool calling 完成所有任务，先跑通核心链路。

### 阶段 2：拆出 Observer Agent

当 Main Agent 上下文过长或感知逻辑复杂时，将感知类工具（parse_dom/screenshot）独立为 Observer Agent。Main Agent 不再直接感知页面。

### 阶段 3：拆出 Verifier Agent

操作后验证独立为 Verifier Agent。Main Agent 变为纯 Planner 角色。

每次只拆一个 Agent，用 asyncio 编排，确保每步都能跑通。

## 10. MVP 范围

- 单体 Agent + 9 个浏览器工具（含 CDP 降级）+ SidePanel 聊天界面
- AI 模式 / 人工模式切换（遮罩层）
- 核心链路：用户输入 → WS → Agent 推理 → 工具下发 → Extension 执行 → 结果回传
- 元素打标机制（backend-id），减少 Token 消耗
- 页面导航就绪握手，防止 Content Script 断裂
- 心跳保活，防止 Service Worker 休眠
- 支持 DOM 感知 + 截图感知的混合模式，CDP 坐标点击降级
- LLM/VLM 可配置切换
