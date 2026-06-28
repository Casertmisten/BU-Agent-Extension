 事件流展示增强 Implementation Plan

 > **For Codex:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

 **Goal:** 为 agent 多步任务提供实时步骤进度展示，包括思考过程（reflection）、工具调用详情（step card）、细粒度状态通知（activity_status），参考 page-agent 的卡片体系。

 **Architecture:** 后端在 `agent.py` 的流式循环中新增 `activity_status` 和 `reflection` 两种事件类型，通过现有 WebSocket 透传到前端。前端重构 `EventCards.tsx`，以 `StepCard` + `ReflectionSection` + `RawSection` + 增强 `ActivityCard` 替换现有的 `TimelineNode` + `ToolCallTimeline`，由 `ChatView.tsx` 统一编排。

 **Tech Stack:** Python (agentscope, pytest) / TypeScript (React, Tailwind CSS, lucide-react)

 ---

 ### Task 1: 后端 — 扩展 `agent.py` 流式事件，新增 `activity_status` 和 `reflection`

 **Files:**
 - Modify: `agent/agent.py:106-170`（`run()` 方法）
 - Test: `tests/test_agent.py`

 **Step 1: 编写辅助类和测试**

 在 `tests/test_agent.py` 顶部 import 区域后追加辅助类：

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

 在文件末尾追加测试 `test_activity_status_events` 和 `test_reflection_event_emitted`：

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
     evt_text.delta = "思考内容..."
     mock_events.append(evt_text)

     evt_start = MagicMock()
     evt_start.type = "TOOL_CALL_START"
     evt_start.tool_call_id = "tc_1"
     evt_start.tool_call_name = "parse_dom"
     mock_events.append(evt_start)

     evt_delta = MagicMock()
     evt_delta.type = "TOOL_CALL_DELTA"
     evt_delta.tool_call_id = "tc_1"
     evt_delta.delta = '{"url": "example.com"}'
     mock_events.append(evt_delta)

     evt_result_delta = MagicMock()
     evt_result_delta.type = "TOOL_RESULT_TEXT_DELTA"
     evt_result_delta.tool_call_id = "tc_1"
     evt_result_delta.delta = "找到 3 个元素"
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
     assert len(status_events) >= 2
     assert status_events[0]["event"]["data"]["status"] == "thinking"
     assert any(e["event"]["data"]["status"] == "executing" for e in status_events)
 ```

 ```python
 @pytest.mark.asyncio
 async def test_reflection_event_emitted():
     """测试 reflection 事件在 TOOL_RESULT_END 后推送。"""
     agent = BrowserAgent(_make_config())
     agent.init()

     mock_events = []
     evt_text = MagicMock()
     evt_text.type = "TEXT_BLOCK_DELTA"
     evt_text.delta = "分析页面结构..."
     mock_events.append(evt_text)

     for evt_type, tid, extra in [
         ("TOOL_CALL_START", "tc_1", {"tool_call_name": "parse_dom"}),
         ("TOOL_CALL_DELTA", "tc_1", {"delta": "{}"}),
         ("TOOL_RESULT_TEXT_DELTA", "tc_1", {"delta": "ok"}),
         ("TOOL_RESULT_END", "tc_1", {"state": "success"}),
     ]:
         evt = MagicMock()
         evt.type = evt_type
         evt.tool_call_id = tid
         for k, v in extra.items():
             setattr(evt, k, v)
         mock_events.append(evt)

     from unittest.mock import patch
     with patch.object(agent._agent, "reply_stream", return_value=AsyncIteratorMock(mock_events)):
         events = []
         async for evt in agent.run("测试"):
             events.append(evt)

     reflections = [e for e in events if e.get("type") == "event" and e["event"]["type"] == "reflection"]
     assert len(reflections) == 1
     assert "分析页面结构" in reflections[0]["event"]["data"]["thinking"]
 ```

 **Step 2: 运行测试确认失败**

 Run: `cd agent-core && uv run pytest tests/test_agent.py::test_activity_status_events -v`
 Expected: FAIL

 **Step 3: 实现 `activity_status` 和 `reflection` 事件推送**

 修改 `agent/agent.py` 的 `run()` 方法：

 1. 在 `_step_index = 0` 之后新增 `_text_buf = ""`
 2. 循环前推送 `activity_status(thinking)`
 3. `TEXT_BLOCK_DELTA` 分支追加 `_text_buf += evt.delta`
 4. `TOOL_CALL_START` 中 step(running) 前推送 `activity_status(executing)`
 5. `TOOL_RESULT_END` 后检查 `_text_buf` 推送 `reflection` + `activity_status(thinking)`
 6. `[DONE]` 前推送 `activity_status(done)`
 7. `except` 中推送 `activity_status(error)`

 **Step 4: 运行测试确认通过**

 Run: `cd agent-core && uv run pytest tests/test_agent.py -v`
 Expected: 全部 PASS

 **Step 5: Commit**

 ```bash
 git add agent/agent.py tests/test_agent.py
 git commit -m "feat: 新增 activity_status 和 reflection 流式事件"
 ```

 ---

 ### Task 2: 前端 — 扩展类型定义

 **Files:**
 - Modify: `chrome-extension/src/types/index.ts`

 **Step 1: 扩展 `AgentEvent.type` 联合类型**

 将 `type` 从现有值扩展为：
 ```typescript
 type: 'step' | 'observation' | 'error' | 'result' | 'retry' | 'activity' | 'reflection' | 'activity_status'
 ```

 在 `AgentEvent` 接口下方追加：
 ```typescript
 export type ActivityStatus = 'idle' | 'thinking' | 'executing' | 'retrying' | 'error' | 'done'

 export interface ReflectionData {
   thinking?: string
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
 git commit -m "feat: 扩展 AgentEvent 类型，新增 reflection 和 activity_status"
 ```

 ---

 ### Task 3: 前端 — 更新 `useWebSocket.ts` 处理新事件

 **Files:**
 - Modify: `chrome-extension/src/hooks/useWebSocket.ts`

 **Step 1: 新增 `activityStatus` 状态**

 - `UseWebSocketReturn` 接口新增 `activityStatus: ActivityStatus`
 - hook 内新增 `const [activityStatus, setActivityStatus] = useState<ActivityStatus>('idle')`
 - import `ActivityStatus`

 **Step 2: 在消息监听器中处理新事件类型**

 替换 `message.type === 'event'` 分支：
 - `activity_status` 事件 → `setActivityStatus`
 - `reflection` 事件 → 追加到 streaming.events
 - 其他事件（step/error/retry）→ 原有逻辑追加到 streaming.events

 **Step 3: 重置 activityStatus**

 在 `[DONE]` 处理和 `sendTask` 中追加 `setActivityStatus('idle')`。

 **Step 4: 更新返回值**

 return 对象追加 `activityStatus`。

 **Step 5: 验证编译 + Commit**

 ```bash
 git add chrome-extension/src/hooks/useWebSocket.ts
 git commit -m "feat: useWebSocket 新增 activityStatus 状态和 reflection 事件处理"
 ```

 ---

 ### Task 4: 前端 — 重写 `EventCards.tsx`

 **Files:**
 - Rewrite: `chrome-extension/src/components/EventCards.tsx`

 保留 `ToolIcon`、`toolDisplayName`、`formatInputSummary` 辅助函数不变。

 **新增组件：**

 1. **`ReflectionSection`** — 3 列 grid 布局展示思考过程，每个字段单行截断 hover 展开，半透明背景
 2. **`RawSection`** — 可折叠调试面板，标签页切换 Request/Response，复制按钮，JSON 格式化
 3. **`StepCard`** — 替换 `TimelineNode`：左侧蓝色边框 + 步骤编号 + 工具图标 + 状态图标 + 参数摘要 + 结果展示 + 嵌入 ReflectionSection 和 RawSection
 4. **增强 `ActivityCard`** — 支持 thinking/executing/retrying/error 多状态，不同颜色和图标
 5. **`EventCard`（统一入口）** — 根据 event.type 分发到 StepCard / ReflectionSection / ErrorCard / RetryCard
 6. **`EventStream`（列表容器）** — 替换 `ToolCallTimeline`，过滤 activity_status，渲染所有可见事件

 删除 `TimelineNode` 和 `ToolCallTimeline`。

 **参考实现：** `ui参考/components/cards.tsx` 中的 `ReflectionSection`、`RawSection`、`StepCard`

 **验证 + Commit**

 ```bash
 git add chrome-extension/src/components/EventCards.tsx
 git commit -m "feat: 重写 EventCards，新增 StepCard/ReflectionSection/RawSection/增强 ActivityCard"
 ```

 ---

 ### Task 5: 前端 — 更新 `ChatView.tsx` 和 `App.tsx`

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

 ### Task 6: 端到端验证

 1. 启动后端：`cd agent-core && uv run python -m server`
 2. 构建扩展：`cd chrome-extension && npx wxt build`，加载到 Chrome
 3. 功能验证清单：
    - [ ] ActivityCard 显示 "Agent 正在思考..."（蓝色 Sparkles）
    - [ ] 工具调用时切换到 "Agent 正在执行操作..."
    - [ ] StepCard 正确渲染（蓝色左边框、步骤编号、工具图标）
    - [ ] ReflectionSection 显示思考过程
    - [ ] 展开详情 + Raw 面板
    - [ ] 完成时 ActivityCard 消失
    - [ ] 错误时显示红色错误卡片
