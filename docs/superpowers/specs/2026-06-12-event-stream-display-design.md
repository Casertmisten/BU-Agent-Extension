# 事件流展示增强设计

## 概述

将 agent 从简单的工具调用模式升级为**迭代循环式浏览器自动化代理**。Agent 每一步输出结构化的思考过程（evaluation / memory / next_goal）+ 动作，前端以卡片体系实时展示步骤进度。

### 核心变化

| 维度 | 改造前 | 改造后 |
|------|--------|--------|
| Agent 循环 | 单轮工具调用 | 迭代循环，每步有 evaluation/memory/next_goal |
| 系统提示词 | 简单浏览器操作说明 | 完整的 browser agent prompt（含规则、示例、输出格式） |
| 工具集 | DOM 解析 + CDP 点击 | 增加 `done`、`extract_content`、`go_back`、`switch_tab`、`scroll_element` |
| 事件流 | step + stream | 新增 `reflection`（结构化思考）+ `activity_status`（状态指示） |

## 后端改动

### 1. `agent/prompts.py` — 系统提示词重写

替换为完整的浏览器 Agent 提示词，包含以下部分：

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

### 2. `browser/tools.py` — 工具集扩展

在 `create_browser_tools()` 中新增以下工具：

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

工具返回字典更新为：
```python
return {
    "parse_dom": parse_dom,
    "get_element_info": get_element_info,
    "click_element": click_element,
    "input_text": input_text,
    "scroll_page": scroll_page,
    "scroll_element": scroll_element,  # 新增
    "navigate": navigate,
    "go_back": go_back,                # 新增
    "switch_tab": switch_tab,          # 新增
    "extract_content": extract_content,# 新增
    "wait": wait,
    "screenshot_analyze": screenshot_analyze,
    "cdp_click": cdp_click,
    "done": done,                      # 新增
}
```

### 3. `browser/protocol.py` — 消息类型扩展

`MSG_TYPES` 新增：
```python
MSG_TYPES = frozenset({
    "action",
    "result",
    "heartbeat",
    "page_ready",
    "stream",
    "mode_change",
    "user_message",
    "browser_state",   # 新增：扩展 → Agent：浏览器状态快照
    "tab_change",      # 新增：扩展 → Agent：标签页变化通知
})
```

### 4. `agent/agent.py` — 事件流扩展

#### 4a. Reflection 解析

Agent 每一步输出 JSON（含 evaluation_previous_goal / memory / next_goal / action）。在 `TOOL_RESULT_END` 之后解析 LLM 文本输出中的 JSON，提取 reflection 字段并推送事件。

新增辅助方法：

```python
import re

def _parse_reflection(self, text: str) -> dict | None:
    """从 LLM 文本输出中提取 reflection JSON。"""
    match = re.search(r'\{[^{}]*"evaluation_previous_goal"[^{}]*\}', text, re.DOTALL)
    if not match:
        return None
    try:
        data = json.loads(match.group())
        return {
            "evaluation_previous_goal": data.get("evaluation_previous_goal", ""),
            "memory": data.get("memory", ""),
            "next_goal": data.get("next_goal", ""),
        }
    except json.JSONDecodeError:
        return None
```

#### 4b. 事件推送逻辑

在 `run()` 流式循环中新增两种事件类型：

**`activity_status` 事件** — 细粒度状态通知：
```json
{"type": "event", "event": {"type": "activity_status", "data": {"status": "thinking"}}}
{"type": "event", "event": {"type": "activity_status", "data": {"status": "executing"}}}
{"type": "event", "event": {"type": "activity_status", "data": {"status": "retrying"}}}
```

状态枚举：`thinking` | `executing` | `retrying` | `error` | `done`

**`reflection` 事件** — 思考过程：
```json
{
  "type": "event",
  "event": {
    "type": "reflection",
    "data": {
      "evaluation_previous_goal": "成功点击了搜索按钮",
      "memory": "用户需要搜索xxx",
      "next_goal": "在搜索框中输入关键词"
    }
  }
}
```

#### 4c. 修改后的 run() 核心逻辑

```python
async def run(self, text: str):
    """执行用户指令，流式返回事件字典。"""
    if self._busy:
        yield {"type": "stream", "content": "[BUSY] Agent 正在工作中..."}
        return

    self._busy = True
    _tool_calls: dict[str, dict] = {}
    _step_index = 0
    _text_buf = ""  # 累积 LLM 文本输出，用于提取 reflection

    try:
        # 推送初始 thinking 状态
        yield {
            "type": "event",
            "event": {"type": "activity_status", "data": {"status": "thinking"}},
        }

        async for evt in self._agent.reply_stream(
            [UserMsg(name="user", content=text)]
        ):
            if evt.type == EventType.TEXT_BLOCK_DELTA:
                _text_buf += evt.delta
                yield {"type": "stream", "content": evt.delta}

            elif evt.type == EventType.TOOL_CALL_START:
                # 在工具调用前推送 reflection（从累积文本中提取）
                reflection = self._parse_reflection(_text_buf)
                if reflection:
                    yield {
                        "type": "event",
                        "event": {"type": "reflection", "data": reflection, "timestamp": 0},
                    }
                _text_buf = ""  # 重置文本缓冲

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

            elif evt.type == EventType.TOOL_RESULT_TEXT_DELTA:
                tc = _tool_calls.get(evt.tool_call_id)
                if tc:
                    tc["result_buf"] += evt.delta

            elif evt.type == EventType.TOOL_RESULT_END:
                tc = _tool_calls.get(evt.tool_call_id)
                if tc:
                    try:
                        parsed_args = json.loads(tc["args_buf"]) if tc["args_buf"] else {}
                    except (json.JSONDecodeError, TypeError):
                        parsed_args = tc["args_buf"]
                    status = "done" if str(evt.state) == "success" else "error"
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

                # 工具调用结束后推送 thinking 状态（等待下一轮 LLM 输出）
                yield {
                    "type": "event",
                    "event": {"type": "activity_status", "data": {"status": "thinking"}},
                }

        # 流式结束后，推送最终的 reflection（如果有剩余文本）
        reflection = self._parse_reflection(_text_buf)
        if reflection:
            yield {
                "type": "event",
                "event": {"type": "reflection", "data": reflection, "timestamp": 0},
            }

        yield {"type": "stream", "content": "[DONE]"}
        yield {
            "type": "event",
            "event": {"type": "activity_status", "data": {"status": "done"}},
        }
    except Exception as e:
        log.error("Agent 执行错误: %s", e, exc_info=True)
        yield {
            "type": "event",
            "event": {"type": "activity_status", "data": {"status": "error"}},
        }
        yield {"type": "error", "message": f"Agent error: {e}"}
    finally:
        self._busy = False
```

**事件推送顺序**：
```
activity_status(thinking)           <- run 开始时
  -> reflection(eval/memory/goal)   <- 从 LLM 文本输出解析
activity_status(executing)          <- TOOL_CALL_START
  -> step(running, action=name)
  -> step(done/error, input, output)
activity_status(thinking)           <- TOOL_RESULT_END 后
  -> reflection(eval/memory/goal)   <- 下一轮 LLM 文本
activity_status(executing)
  -> ...
stream([DONE])
activity_status(done)               <- 任务完成
```

## 前端改动

### `types/index.ts`

```typescript
export interface AgentEvent {
  type: 'step' | 'observation' | 'error' | 'result' | 'retry' | 'activity' | 'reflection' | 'activity_status'
  data: Record<string, unknown>
  timestamp: number
}
```

新增 `reflection` 和 `activity_status` 类型。

### `EventCards.tsx` — 重构

替换 `TimelineNode` + `ToolCallTimeline`，新增以下组件：

**`StepCard`** — 单个工具调用步骤：
- 左侧蓝色边框（`border-l-2 border-blue-500`）
- 步骤编号（自动递增）
- 工具图标 + 名称 + 状态图标（Loader2/XCircle/CheckCircle）
- 参数摘要（单行截断，hover 展开）
- 结果展示（grid 布局）
- 支持 ReflectionSection 和 RawSection 嵌入

**`ReflectionSection`** — 思考过程：
- 3列 grid 布局
- 三个字段：evaluation_previous_goal、memory、next_goal
- 每个字段单行截断，hover 展开
- 半透明背景，缩小字号

**`RawSection`** — 调试面板：
- 可折叠区域，默认收起
- 标签页切换：Request / Response
- 复制按钮
- JSON 格式化展示

**`ActivityCard`（增强版）** — 多状态指示器：
- `thinking`：蓝色 Sparkles + "Agent 正在思考..."
- `executing`：蓝色 Sparkles + "Agent 正在执行操作..."
- `retrying`：amber RefreshCw + "重试中..."
- `error`：红色 XCircle + "出错了"
- `done`：绿色 CheckCircle + "完成"

**`EventCard`（统一入口）**：
- 根据 event.type 分发到 StepCard / ReflectionSection / ErrorCard / RetryCard
- 按事件顺序渲染

保留 `ToolIcon`、`toolDisplayName`、`formatInputSummary` 辅助函数。

### `ChatView.tsx`

`MessageBubble`（agent）内的事件展示改为：
- 遍历 message.events，按顺序渲染 EventCard
- streaming 时在底部显示增强版 ActivityCard

### `useWebSocket.ts`

新增状态：
```typescript
const [activityStatus, setActivityStatus] = useState<'idle' | 'thinking' | 'executing' | 'retrying' | 'error'>('idle')
```

事件处理扩展：
- `activity_status` -> 更新 activityStatus
- `reflection` -> 追加到 streaming 消息的 events
- 返回值新增 `activityStatus`

## 展示布局

agent 消息气泡结构：
```
+-------------------------------------+
| [agent 文本回复]                      |
|                                     |
| +- StepCard #1 ------------------+ |
| | +- ReflectionSection ---------+ | |
| | | eval  | memory | next_goal  | | |
| | +-----------------------------+ | |
| | 解析页面  完成                   | |
| |   参数: url: example.com        | |
| |   结果: 找到 3 个元素            | |
| | > Raw (可展开)                  | |
| +---------------------------------+ |
|                                     |
| +- StepCard #2 ------------------+ |
| | 点击元素  完成                   | |
| |   参数: selector: #search       | |
| +---------------------------------+ |
|                                     |
| +- ActivityCard -----------------+ |
| | Agent 正在思考...               | |
| +---------------------------------+ |
+-------------------------------------+
```

## 文件改动清单

| 文件 | 改动类型 |
|------|----------|
| `agent-core/agent/prompts.py` | 重写：完整 browser agent 系统提示词 |
| `agent-core/agent/agent.py` | 修改：新增 reflection 解析 + activity_status 事件 |
| `agent-core/browser/tools.py` | 修改：新增 done / extract_content / go_back / switch_tab / scroll_element |
| `agent-core/browser/protocol.py` | 修改：新增 browser_state / tab_change 消息类型 |
| `chrome-extension/src/types/index.ts` | 修改：扩展 AgentEvent.type |
| `chrome-extension/src/components/EventCards.tsx` | 重写：StepCard + ReflectionSection + RawSection + 增强 ActivityCard |
| `chrome-extension/src/components/ChatView.tsx` | 修改：使用新 EventCard + activityStatus |
| `chrome-extension/src/hooks/useWebSocket.ts` | 修改：新增 activityStatus 状态和事件处理 |

## 不涉及的改动

- 不改 `server.py`（透传 JSON，无需修改）
- 不改 `background.ts`（透传消息，无需修改）
- 不改配置面板、历史记录等无关组件
- 不引入新的 npm 依赖
