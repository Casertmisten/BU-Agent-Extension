# 事件流展示增强 Implementation Plan

> **For Codex:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 将 agent 从简单工具调用模式升级为迭代循环式浏览器自动化代理，支持结构化思考过程（evaluation/memory/next_goal）、新增浏览器工具（done/extract_content/go_back/switch_tab/scroll_element）、新增流式事件（reflection/activity_status），前端以 StepCard + ReflectionSection 卡片体系实时展示。

**Architecture:** 后端分四层改造：(1) `prompts.py` 重写为完整 browser agent 提示词，要求 LLM 每步输出结构化 JSON；(2) `tools.py` 新增 5 个工具；(3) `protocol.py` 扩展消息类型；(4) `agent.py` 新增 reflection 解析 + activity_status 事件推送。前端重构 `EventCards.tsx`，以 StepCard + ReflectionSection + RawSection + 增强 ActivityCard 替换现有 TimelineNode + ToolCallTimeline。

**Tech Stack:** Python (agentscope, pytest) / TypeScript (React, Tailwind CSS, lucide-react)

---

### Task 1: 后端 — 重写 `agent/prompts.py` 系统提示词

**Files:**
- Rewrite: `agent/prompts.py`

**Step 1: 替换 SYSTEM_PROMPT 为完整 browser agent 提示词**

将 `agent/prompts.py` 的 `SYSTEM_PROMPT` 替换为：

```python
SYSTEM_PROMPT = """<intro>
你是一个被设计为在迭代循环中运行的 AI 代理，用于自动化浏览器任务。
你的最终目标是完成 <user_request> 中提供的任务。

你擅长完成以下任务：
1. 导航复杂网站并提取精确信息。
2. 自动化表单提交和交互式网页操作。
3. 收集并保存信息。
4. 在代理循环中高效运作。
5. 高效执行多样的网页任务。
</intro>

<language_settings>
- 默认工作语言：英语
- 使用用户正在使用的语言。使用用户的语言回复。
</language_settings>

<input>
在每一步中，你的输入将包括：
1. <agent_history>：包含你之前的操作及其结果的事件流（按时间顺序）。
2. <agent_state>：当前的 <user_request> 和 <step_info>。
3. <browser_state>：标签页、当前标签页、当前 URL、可用于操作的带索引的可交互元素，以及可见的页面内容。
</input>

<browser_rules>
- 仅与分配了数字 [索引] 的元素交互。
- 仅使用明确提供的索引。
- 如果在输入文本操作后页面发生变化，分析是否需要与新元素交互。
- 默认只有可见视口中的元素会被列出。如果相关内容在屏幕外，使用滚动操作。
- 如果出现验证码，告知用户你无法解决验证码，完成任务并要求用户解决。
- 如果预期的元素缺失，尝试滚动或向后导航。
- 如果页面未完全加载，使用 wait 操作。
- 除非必要，不要将同一个操作重复超过 3 次。
- 如果填写输入框后操作序列被中断，通常是因为字段下方弹出了建议。
- 如果用户请求包含特定信息（产品类型、评级、价格等），尝试应用筛选器。
- 没有必要时不要登录页面。
- 任务分为两类：1) 具体的逐步说明（严格遵循） 2) 开放式任务（自主规划）。
</browser_rules>

<task_completion_rules>
在以下情况必须调用 done 操作：
- 完全完成了用户请求时。
- 达到最大步数时。
- 感到卡住或无法解决时。
- 绝对不可能继续时。

- 仅当完整请求已全部完成时，才将 success 设为 true。
- 使用 text 字段传达发现和回复。
- done 操作只能单独调用，不与其他操作一起调用。
</task_completion_rules>

<reasoning_rules>
- 根据 agent_history 进行推理，跟踪朝向 user_request 的进度。
- 分析最近的"下一个目标"和"操作结果"。
- 明确判断上一个操作的成功/失败/不确定性。
- 分析是否卡住（重复相同操作无进展），考虑替代方法。
- 如果遇到困难，向用户寻求帮助。
- 看到相关信息时保存到记忆中。
- 始终思考 user_request，确保步骤与请求一致。
</reasoning_rules>

<output>
你必须输出 JSON 格式：
{
  "evaluation_previous_goal": "对上一个操作进行简洁的一句话分析。说明成功、失败或不确定。",
  "memory": "1-3句关于此步骤和整体进度的简洁记忆。",
  "next_goal": "用一句清晰的话陈述下一个即时目标。",
  "action": {
    "操作名称": { /* 操作参数 */ }
  }
}
</output>
"""
```

**Step 2: Commit**

```bash
git add agent/prompts.py
git commit -m "feat: 重写系统提示词为完整 browser agent prompt"
```

---

### Task 2: 后端 — 扩展 `browser/tools.py` 工具集

**Files:**
- Modify: `browser/tools.py`

**Step 1: 在 `create_browser_tools()` 的 `return` 语句前新增 5 个工具函数**

```python
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

    async def switch_tab(tab_index: int) -> _CompatToolResponse:
        """切换到指定索引的标签页。"""
        result = await conn.send_action({"action": "switch_tab", "tab_index": tab_index})
        return _CompatToolResponse(output=f"Switch to tab {tab_index}: {result.get('status', 'unknown')}")

    async def scroll_element(target_id: str, direction: str = "down", pixels: int = 300) -> _CompatToolResponse:
        """滚动指定可滚动元素。"""
        result = await conn.send_action({
            "action": "scroll_element",
            "target_id": target_id,
            "direction": direction,
            "pixels": pixels,
        })
        return _CompatToolResponse(output=f"Scroll element {target_id}: {result.get('status', 'unknown')}")
```

**Step 2: 更新返回字典**

```python
    return {
        "parse_dom": parse_dom,
        "get_element_info": get_element_info,
        "click_element": click_element,
        "input_text": input_text,
        "scroll_page": scroll_page,
        "scroll_element": scroll_element,
        "navigate": navigate,
        "go_back": go_back,
        "switch_tab": switch_tab,
        "extract_content": extract_content,
        "wait": wait,
        "screenshot_analyze": screenshot_analyze,
        "cdp_click": cdp_click,
        "done": done,
    }
```

**Step 3: 验证导入无报错**

Run: `cd agent-core && uv run python -c "from browser.tools import create_browser_tools; print('OK')"`
Expected: OK

**Step 4: Commit**

```bash
git add browser/tools.py
git commit -m "feat: 新增 done/extract_content/go_back/switch_tab/scroll_element 工具"
```

---

### Task 3: 后端 — 扩展 `browser/protocol.py` 消息类型

**Files:**
- Modify: `browser/protocol.py`

**Step 1: 在 `MSG_TYPES` 中新增 `browser_state` 和 `tab_change`**

将 `MSG_TYPES` 替换为：

```python
MSG_TYPES = frozenset({
    "action",
    "result",
    "heartbeat",
    "page_ready",
    "stream",
    "mode_change",
    "user_message",
    "browser_state",
    "tab_change",
})
```

**Step 2: Commit**

```bash
git add browser/protocol.py
git commit -m "feat: 新增 browser_state/tab_change 消息类型"
```

---

### Task 4: 后端 — 扩展 `agent/agent.py` 流式事件

**Files:**
- Modify: `agent/agent.py`
- Test: `tests/test_agent.py`

**Step 1: 编写测试**

在 `tests/test_agent.py` 顶部 import 区域后追加：

```python
class AsyncIteratorMock:
    """模拟 async for 迭代器。"""
    def __init__(self, items):
        self._items = iter(items)
    def __aiter__(self):
        return self
    async def __anext__(self):
        try:
            return next(self._items)
        except StopIteration:
            raise StopAsyncIteration
```

在文件末尾追加 3 个测试：

```python
@pytest.mark.asyncio
async def test_activity_status_events():
    """测试 activity_status 事件在正确时机推送。"""
    from unittest.mock import MagicMock, patch

    agent = BrowserAgent(_make_config())
    agent.init()

    mock_events = []

    evt_text = MagicMock()
    evt_text.type = "TEXT_BLOCK_DELTA"
    evt_text.delta = "思考中..."
    mock_events.append(evt_text)

    evt_start = MagicMock()
    evt_start.type = "TOOL_CALL_START"
    evt_start.tool_call_id = "tc_1"
    evt_start.tool_call_name = "parse_dom"
    mock_events.append(evt_start)

    evt_delta = MagicMock()
    evt_delta.type = "TOOL_CALL_DELTA"
    evt_delta.tool_call_id = "tc_1"
    evt_delta.delta = "{}"
    mock_events.append(evt_delta)

    evt_result_delta = MagicMock()
    evt_result_delta.type = "TOOL_RESULT_TEXT_DELTA"
    evt_result_delta.tool_call_id = "tc_1"
    evt_result_delta.delta = "ok"
    mock_events.append(evt_result_delta)

    evt_end = MagicMock()
    evt_end.type = "TOOL_RESULT_END"
    evt_end.tool_call_id = "tc_1"
    evt_end.state = "success"
    mock_events.append(evt_end)

    with patch.object(agent._agent, "reply_stream", return_value=AsyncIteratorMock(mock_events)):
        events = []
        async for evt in agent.run("测试指令"):
            events.append(evt)

    status_events = [e for e in events if e.get("type") == "event" and e["event"]["type"] == "activity_status"]
    assert len(status_events) >= 3
    assert status_events[0]["event"]["data"]["status"] == "thinking"
    assert any(e["event"]["data"]["status"] == "executing" for e in status_events)
    assert any(e["event"]["data"]["status"] == "done" for e in status_events)
```

```python
@pytest.mark.asyncio
async def test_reflection_event_emitted():
    """测试 reflection 事件在 TOOL_CALL_START 前从文本中解析并推送。"""
    from unittest.mock import MagicMock, patch

    agent = BrowserAgent(_make_config())
    agent.init()

    mock_events = []

    reflection_text = '{"evaluation_previous_goal": "成功导航", "memory": "用户要搜索xxx", "next_goal": "输入关键词"}'
    evt_text = MagicMock()
    evt_text.type = "TEXT_BLOCK_DELTA"
    evt_text.delta = reflection_text
    mock_events.append(evt_text)

    for evt_type, tid, extra in [
        ("TOOL_CALL_START", "tc_1", {"tool_call_name": "input_text"}),
        ("TOOL_CALL_DELTA", "tc_1", {"delta": '{"target_id": "5", "text": "test"}'}),
        ("TOOL_RESULT_TEXT_DELTA", "tc_1", {"delta": "ok"}),
        ("TOOL_RESULT_END", "tc_1", {"state": "success"}),
    ]:
        evt = MagicMock()
        evt.type = evt_type
        evt.tool_call_id = tid
        for k, v in extra.items():
            setattr(evt, k, v)
        mock_events.append(evt)

    with patch.object(agent._agent, "reply_stream", return_value=AsyncIteratorMock(mock_events)):
        events = []
        async for evt in agent.run("测试"):
            events.append(evt)

    reflections = [e for e in events if e.get("type") == "event" and e["event"]["type"] == "reflection"]
    assert len(reflections) == 1
    assert reflections[0]["event"]["data"]["evaluation_previous_goal"] == "成功导航"
    assert reflections[0]["event"]["data"]["memory"] == "用户要搜索xxx"
    assert reflections[0]["event"]["data"]["next_goal"] == "输入关键词"
```

```python
@pytest.mark.asyncio
async def test_parse_reflection():
    """测试 _parse_reflection 辅助方法。"""
    agent = BrowserAgent(_make_config())

    text = '一些文本 {"evaluation_previous_goal": "成功", "memory": "记忆", "next_goal": "目标"} 更多文本'
    result = agent._parse_reflection(text)
    assert result is not None
    assert result["evaluation_previous_goal"] == "成功"
    assert result["memory"] == "记忆"
    assert result["next_goal"] == "目标"

    assert agent._parse_reflection("无 JSON 文本") is None
    assert agent._parse_reflection("") is None
```

**Step 2: 运行测试确认失败**

Run: `cd agent-core && uv run pytest tests/test_agent.py::test_activity_status_events tests/test_agent.py::test_reflection_event_emitted tests/test_agent.py::test_parse_reflection -v`
Expected: FAIL（方法/逻辑不存在）

**Step 3: 实现 `_parse_reflection` 方法和修改 `run()` 方法**

1. 在 `agent.py` 顶部追加 `import re`
2. 在 `BrowserAgent` 类中新增 `_parse_reflection` 方法
3. 修改 `run()` 方法：新增 `_text_buf`、初始 `activity_status(thinking)`、TOOL_CALL_START 前解析 reflection 并推送、TOOL_CALL_START 时推送 `activity_status(executing)`、TOOL_RESULT_END 后推送 `activity_status(thinking)`、流结束后推送 `activity_status(done)`、异常推送 `activity_status(error)`

具体代码参考设计文档 `4c. 修改后的 run() 核心逻辑` 部分。

**Step 4: 运行测试确认通过**

Run: `cd agent-core && uv run pytest tests/test_agent.py -v`
Expected: 全部 PASS

**Step 5: Commit**

```bash
git add agent/agent.py tests/test_agent.py
git commit -m "feat: agent.py 新增 _parse_reflection + activity_status/reflection 事件推送"
```

---

### Task 5: 前端 — 扩展类型定义

**Files:**
- Modify: `chrome-extension/src/types/index.ts`

**Step 1: 扩展 `AgentEvent.type` 联合类型**

将 `type` 扩展为：
```typescript
type: 'step' | 'observation' | 'error' | 'result' | 'retry' | 'activity' | 'reflection' | 'activity_status'
```

在 `AgentEvent` 接口下方追加：
```typescript
export type ActivityStatus = 'idle' | 'thinking' | 'executing' | 'retrying' | 'error' | 'done'

export interface ReflectionData {
  evaluation_previous_goal?: string
  memory?: string
  next_goal?: string
}
```

**Step 2: 验证编译**

Run: `cd chrome-extension && npx tsc --noEmit 2>&1 | head -20`
Expected: 无新增类型错误

**Step 3: Commit**

```bash
git add chrome-extension/src/types/index.ts
git commit -m "feat: 扩展 AgentEvent 类型，新增 reflection/activity_status/ReflectionData"
```

---

### Task 6: 前端 — 更新 `useWebSocket.ts` 处理新事件

**Files:**
- Modify: `chrome-extension/src/hooks/useWebSocket.ts`

**Step 1: 新增 `activityStatus` 状态**

- `UseWebSocketReturn` 接口新增 `activityStatus: ActivityStatus`
- hook 内新增 `const [activityStatus, setActivityStatus] = useState<ActivityStatus>('idle')`
- import `ActivityStatus`

**Step 2: 在消息监听器中处理新事件类型**

替换 `message.type === 'event'` 分支：
- `activity_status` 事件 → `setActivityStatus(data.status)`
- `reflection` 事件 → 追加到 streaming.events
- 其他事件（step/error/retry）→ 原有逻辑追加到 streaming.events

**Step 3: 重置 activityStatus**

在 `[DONE]` 处理和 `sendTask` 中追加 `setActivityStatus('idle')`。

**Step 4: 更新返回值**

return 对象追加 `activityStatus`。

**Step 5: 验证编译 + Commit**

```bash
cd chrome-extension && npx tsc --noEmit
git add chrome-extension/src/hooks/useWebSocket.ts
git commit -m "feat: useWebSocket 新增 activityStatus 状态和 reflection 事件处理"
```

---

### Task 7: 前端 — 重写 `EventCards.tsx`

**Files:**
- Rewrite: `chrome-extension/src/components/EventCards.tsx`

保留 `ToolIcon`、`toolDisplayName`、`formatInputSummary` 辅助函数不变。

**新增组件：**

1. **`ReflectionSection`** — 3 列 grid 布局展示 evaluation_previous_goal / memory / next_goal，每个字段单行截断 hover 展开，半透明背景
2. **`RawSection`** — 可折叠调试面板，标签页切换 Request/Response，复制按钮，JSON 格式化
3. **`StepCard`** — 替换 `TimelineNode`：左侧蓝色边框 + 步骤编号 + 工具图标 + 状态图标 + 参数摘要 + 结果展示 + 嵌入 ReflectionSection 和 RawSection
4. **增强 `ActivityCard`** — 支持 thinking/executing/retrying/error/done 多状态，不同颜色和图标
5. **`EventCard`（统一入口）** — 根据 event.type 分发到 StepCard / ReflectionSection / ErrorCard / RetryCard
6. **`EventStream`（列表容器）** — 替换 `ToolCallTimeline`，过滤 activity_status，渲染所有可见事件

删除 `TimelineNode` 和 `ToolCallTimeline`。

**参考实现：** `ui参考/components/cards.tsx` 中的 `ReflectionSection`、`RawSection`、`StepCard`

**验证 + Commit**

```bash
cd chrome-extension && npx tsc --noEmit
git add chrome-extension/src/components/EventCards.tsx
git commit -m "feat: 重写 EventCards，新增 StepCard/ReflectionSection/RawSection/增强 ActivityCard"
```

---

### Task 8: 前端 — 更新 `ChatView.tsx` 和 `App.tsx`

**Files:**
- Modify: `chrome-extension/src/components/ChatView.tsx`
- Modify: `chrome-extension/src/entrypoints/sidepanel/App.tsx`

**Step 1: ChatView.tsx**

- import 改为 `{ ActivityCard, EventStream }` 替换 `{ ActivityCard, ToolCallTimeline }`
- `ChatViewProps` 新增 `activityStatus: string`
- `<ActivityCard />` → `<ActivityCard status={activityStatus} />`
- `<ToolCallTimeline events={...} />` → `<EventStream events={...} />`

**Step 2: App.tsx**

- 从 `useWebSocket()` 解构 `activityStatus`
- 传入 `<ChatView activityStatus={activityStatus} />`

**Step 3: 验证编译和构建**

```bash
cd chrome-extension && npx tsc --noEmit
cd chrome-extension && npx wxt build
```

**Step 4: Commit**

```bash
git add chrome-extension/src/components/ChatView.tsx chrome-extension/src/entrypoints/sidepanel/App.tsx
git commit -m "feat: ChatView 集成 EventStream 和增强 ActivityCard"
```

---

### Task 9: 端到端验证

1. 启动后端：`cd agent-core && uv run python -m server`
2. 构建扩展：`cd chrome-extension && npx wxt build`，加载到 Chrome
3. 功能验证清单：
   - [ ] Agent 使用新提示词输出结构化 JSON
   - [ ] ActivityCard 显示 "Agent 正在思考..."（蓝色 Sparkles）
   - [ ] 工具调用时切换到 "Agent 正在执行操作..."
   - [ ] StepCard 正确渲染（蓝色左边框、步骤编号、工具图标）
   - [ ] ReflectionSection 显示 evaluation_previous_goal / memory / next_goal
   - [ ] 展开详情 + Raw 面板
   - [ ] `done` 工具正确触发完成状态
   - [ ] 新工具（go_back / switch_tab / scroll_element / extract_content）可被调用
   - [ ] 完成时 ActivityCard 显示 "完成"（绿色 CheckCircle）
   - [ ] 错误时显示红色错误卡片
