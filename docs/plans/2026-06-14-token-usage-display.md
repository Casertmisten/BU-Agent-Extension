# Token 消耗显示实施计划

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 在 Agent 回复气泡后显示一轮对话的总 token 消耗（input/output）。

**Architecture:** 后端 agent.py 的 run() 累加 agentscope `MODEL_CALL_END` 事件的 token，在 `[DONE]` 前 yield 一个 `token_usage` event；前端复用现有 event 通道累积进 message.events，MessageBlock 从 events 提取并在气泡后渲染弱化文字胶囊。

**Tech Stack:** Python（pytest-asyncio）/ TypeScript（React，agentscope 事件流）

**设计文档：** `docs/plans/2026-06-14-token-usage-display-design.md`

**已确认的关键事实：**
- agentscope 事件：`EventType.MODEL_CALL_END`，字段 `input_tokens: int`、`output_tokens: int`
- 前端 events 通道已通（step/reflection/activity_status 走同路径），token_usage 复用它，零新 WS 消息类型
- `MessageBlock.tsx:37` 现有 filter：`e.type !== 'activity_status'`，需扩展排除 `token_usage`
- `test_agent.py` 已有 `AsyncIteratorMock`、`_make_config`、`BrowserAgent` 构造模式可复用
- 所有命令在 `agent-core/` 下用 `.venv/bin/python -m pytest`、在 `chrome-extension/` 下用 `npm run build`

---

### Task 1: 后端 token 累加（agent.py）—— TDD

**Files:**
- Test: `agent-core/tests/test_agent.py`（新增测试，复用现有 `AsyncIteratorMock`/`_make_config`）
- Modify: `agent-core/agent/agent.py`（`run()` 方法）

**Step 1: 写失败测试**

在 `tests/test_agent.py` 末尾追加：

```python
import asyncio
from unittest.mock import MagicMock, patch
from agentscope.event import EventType


def test_run_yields_token_usage():
    """run() 应累加 MODEL_CALL_END 的 token，并在 [DONE] 前 yield token_usage 事件。"""
    agent = BrowserAgent(_make_config())
    agent.init()

    # 构造假事件流：2 次 MODEL_CALL_END + 1 段文本 + done 工具
    fake_events = [
        MagicMock(type=EventType.MODEL_CALL_END, input_tokens=5000, output_tokens=200),
        MagicMock(type=EventType.TEXT_BLOCK_DELTA, delta="分析中"),
        MagicMock(type=EventType.MODEL_CALL_END, input_tokens=5200, output_tokens=150),
        MagicMock(type=EventType.TOOL_CALL_START, tool_call_id="t1", tool_call_name="done"),
        MagicMock(type=EventType.TOOL_RESULT_END, tool_call_id="t1", state="success"),
    ]

    async def collect():
        results = []
        with patch.object(agent._agent, "reply_stream", return_value=AsyncIteratorMock(fake_events)):
            async for item in agent.run("测试指令"):
                results.append(item)
        return results

    results = asyncio.run(collect())

    # 找到 token_usage 事件
    token_events = [r for r in results
                    if r.get("type") == "event"
                    and r.get("event", {}).get("type") == "token_usage"]
    assert len(token_events) == 1
    assert token_events[0]["event"]["data"]["input"] == 10200
    assert token_events[0]["event"]["data"]["output"] == 350

    # token_usage 应在 [DONE] 之前
    tu_idx = next(i for i, r in enumerate(results)
                  if r.get("event", {}).get("type") == "token_usage")
    done_idx = next(i for i, r in enumerate(results)
                    if r.get("type") == "stream" and r.get("content") == "[DONE]")
    assert tu_idx < done_idx
```

**Step 2: 运行测试确认失败**

Run（在 `agent-core/` 下）:
```bash
.venv/bin/python -m pytest tests/test_agent.py::test_run_yields_token_usage -v
```
Expected: FAIL（token_usage 事件不存在，`len(token_events) == 1` 断言失败）。

**Step 3: 实现 token 累加**

在 `agent-core/agent/agent.py` 的 `run()` 方法里：

3a. 在 `_text_buf = ""` 那一行（约 165 行）之后，加累加器初始化：
```python
        _total_input_tokens = 0
        _total_output_tokens = 0
```

3b. 在 `async for evt in self._agent.reply_stream(...)` 循环里，在 `if evt.type == EventType.TEXT_BLOCK_DELTA:` **之前**，加 MODEL_CALL_END 分支：
```python
                if evt.type == EventType.MODEL_CALL_END:
                    it = getattr(evt, "input_tokens", None)
                    ot = getattr(evt, "output_tokens", None)
                    if isinstance(it, int):
                        _total_input_tokens += it
                    if isinstance(ot, int):
                        _total_output_tokens += ot
```

3c. 在 `yield {"type": "stream", "content": "[DONE]"}`（约 281 行）**之前**，加 token_usage 事件：
```python
            yield {
                "type": "event",
                "event": {
                    "type": "token_usage",
                    "data": {
                        "input": _total_input_tokens,
                        "output": _total_output_tokens,
                    },
                    "timestamp": 0,
                },
            }
```

**Step 4: 运行测试确认通过**

Run:
```bash
.venv/bin/python -m pytest tests/test_agent.py::test_run_yields_token_usage -v
```
Expected: PASS。

**Step 5: 运行全量 agent 测试，确认无回归**

Run:
```bash
.venv/bin/python -m pytest tests/test_agent.py -v
```
Expected: 全部 PASS（`test_parse_reflection` 是预存失败，与本特性无关，忽略）。

**Step 6: Commit**

```bash
git add agent-core/agent/agent.py agent-core/tests/test_agent.py
git commit -m "feat(agent): run() 累加 MODEL_CALL_END token，[DONE] 前发送 token_usage 事件"
```

---

### Task 2: 前端类型扩展（types.ts）

**Files:**
- Modify: `chrome-extension/src/types/index.ts`

**Step 1: AgentEvent.type 联合类型加 token_usage**

把 `AgentEvent` 接口（约 35-40 行）的 type 字段：
```ts
  type: 'step' | 'observation' | 'error' | 'result' | 'retry' | 'activity' | 'reflection' | 'activity_status'
```
改为：
```ts
  type: 'step' | 'observation' | 'error' | 'result' | 'retry' | 'activity' | 'reflection' | 'activity_status' | 'token_usage'
```

**Step 2: 类型检查**

Run（在 `chrome-extension/` 下）:
```bash
npx tsc --noEmit
```
Expected: 无新错误（仅预存的 `@radix-ui/react-label`/`react-separator` 缺包错误）。

**Step 3: Commit**

```bash
git add chrome-extension/src/types/index.ts
git commit -m "feat(types): AgentEvent.type 加 token_usage"
```

---

### Task 3: 前端渲染（MessageBlock.tsx）

**Files:**
- Modify: `chrome-extension/src/components/MessageBlock.tsx:37-59`

**Step 1: 提取 token_usage 并扩展 visibleEvents 过滤**

把第 37 行：
```tsx
  const visibleEvents = message.events?.filter(e => e.type !== 'activity_status') || []
```
改为（提取 tokenUsage + 扩展过滤）：
```tsx
  const tokenUsage = message.events?.find(e => e.type === 'token_usage')?.data
  const visibleEvents = message.events?.filter(
    e => e.type !== 'activity_status' && e.type !== 'token_usage'
  ) || []
```

**Step 2: 在内容气泡后渲染 token 胶囊**

把 agent 消息的 return 块（约 53-59 行）：
```tsx
      {/* Agent 内容气泡 */}
      {displayContent && (
        <div className="flex justify-start shrink-0">
          <div className="max-w-[85%] rounded-xl rounded-bl-sm border bg-card px-3 py-2 text-xs prose prose-xs prose-sm:max-w-none prose-p:my-1 prose-ul:my-1 prose-ol:my-1 prose-li:my-0.5 prose-pre:my-1 prose-headings:my-1 shadow-sm">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{displayContent}</ReactMarkdown>
          </div>
        </div>
      )}
    </Fragment>
```
改为（在气泡后加 token 胶囊）：
```tsx
      {/* Agent 内容气泡 */}
      {displayContent && (
        <div className="flex justify-start shrink-0">
          <div className="max-w-[85%] rounded-xl rounded-bl-sm border bg-card px-3 py-2 text-xs prose prose-xs prose-sm:max-w-none prose-p:my-1 prose-ul:my-1 prose-ol:my-1 prose-li:my-0.5 prose-pre:my-1 prose-headings:my-1 shadow-sm">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{displayContent}</ReactMarkdown>
          </div>
        </div>
      )}
      {/* Token 消耗胶囊：一轮对话总 token，弱化元信息 */}
      {tokenUsage && typeof tokenUsage.input === 'number'
        && typeof tokenUsage.output === 'number' && (
        <div className="flex justify-start shrink-0">
          <span className="text-[10px] text-muted-foreground px-3 py-1">
            Token: 入 {tokenUsage.input.toLocaleString()} / 出 {tokenUsage.output.toLocaleString()}
          </span>
        </div>
      )}
    </Fragment>
```

**Step 3: 类型检查 + 构建**

Run（在 `chrome-extension/` 下）:
```bash
npx tsc --noEmit && npm run build
```
Expected: 类型检查无新错误；构建成功。

**Step 4: Commit**

```bash
git add chrome-extension/src/components/MessageBlock.tsx
git commit -m "feat(MessageBlock): Agent 回复气泡后显示 token 消耗胶囊"
```

---

### Task 4: 全量回归 + 构建产物验证

**Step 1: Python 全量测试**

Run（在 `agent-core/` 下）:
```bash
.venv/bin/python -m pytest
```
Expected: 仅 `test_parse_reflection`（预存失败）失败，其余全 PASS，含新增的 `test_run_yields_token_usage`。

**Step 2: content.js 全量测试**

Run（在 `chrome-extension/` 下）:
```bash
npx vitest run
```
Expected: 全 PASS（token 特性不动 content.js，回归应无影响）。

**Step 3: 确认构建产物已含新代码**

Run（在 `chrome-extension/` 下）:
```bash
grep -c "token_usage\|Token:" .output/chrome-mv3/sidepanel.js
```
Expected: ≥1（确认 build 已把 MessageBlock 改动打进产物——避免 parse_page 那次"改了源码没构建"的覆辙）。

**Step 4: 手动集成验证**

用户在浏览器验证：
1. `chrome://extensions` 重新加载扩展（加载新 `.output/chrome-mv3`）
2. 重启 agent-core（加载新 agent.py）
3. 发一条指令，等 Agent 完成
4. 确认 Agent 回复气泡下方出现 `Token: 入 X,XXX / 出 XXX`
5. 数值随对话复杂度合理（多步任务 token 更多）
6. 查看历史会话：旧消息无胶囊、新消息有胶囊

**Step 5: 最终 Commit（如有残留）**

```bash
git add -A && git commit -m "test: token 消耗显示全量回归通过" || echo "无需提交"
```

---

## 完成标准

- [ ] agent.py run() 累加 MODEL_CALL_END token，[DONE] 前 yield token_usage
- [ ] `test_run_yields_token_usage` PASS（数值累加正确、时序在 DONE 前）
- [ ] types.ts 的 AgentEvent.type 含 token_usage
- [ ] MessageBlock 从 events 提取 token_usage，气泡后渲染胶囊
- [ ] visibleEvents 排除 token_usage（不进 ToolStepsPanel）
- [ ] Python 全量除预存 `test_parse_reflection` 外全 PASS
- [ ] chrome-extension 构建成功，产物含 token 代码
- [ ] 手动集成：回复后显示 token 胶囊，历史会话新消息有胶囊
