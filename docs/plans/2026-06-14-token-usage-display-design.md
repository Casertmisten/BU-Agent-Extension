# Token 消耗显示设计

> 日期：2026-06-14
> 状态：已认可，待生成实施计划
> 主题：在 Agent 回复末尾显示一轮对话的总 token 消耗

## 背景与动机

用户希望看到每轮对话消耗了多少 token，作为成本感知。最初设想是显示在每个工具步骤卡片的
Request/Response 行，但深入分析后发现 agentscope 的 token 数据是**模型调用级别**
（`MODEL_CALL_END` 事件），而展示是**工具步骤级别**，两者不是 1:1 对应
（一次推理产生 token，但发生在它决定调用的工具之前）。归属语义复杂、价值有限。

经讨论简化为：**显示一轮对话的总 token 消耗**，位置在 Agent 回复气泡之后。

## 设计决策（已与用户确认）

1. **粒度**：一轮对话（一次 `run(text)` 调用）的总 token，不做步骤级归属。
2. **展示位置**：Agent 回复内容气泡之后，左对齐弱化文字胶囊。
3. **数据通道**：复用现有 event 机制（方案 A），不新增 WS 消息类型。
4. **数据来源**：agentscope 的 `MODEL_CALL_END` 事件，含 input/output tokens。

## §1 后端 token 累加与发送（agent.py）

改动 `agent.py` 的 `run()` 循环：

1. `run()` 开头初始化累加器：`_total_input_tokens = 0`、`_total_output_tokens = 0`
2. `async for evt in reply_stream(...)` 循环里新增分支处理 `MODEL_CALL_END`，
   累加事件的 input/output token（仅当字段为数字时）。
3. `[DONE]` 之前 yield token_usage 事件：
   ```python
   yield {
       "type": "event",
       "event": {
           "type": "token_usage",
           "data": {"input": _total_input_tokens, "output": _total_output_tokens},
           "timestamp": 0,
       },
   }
   ```
4. token 字段的确切名字在实现时读 agentscope 源码确认（`input_tokens`/`output_tokens`）。

**边界处理**：
- 无 MODEL_CALL_END（异常退出）→ 不 yield token_usage，前端无胶囊，无副作用。
- 某次事件缺 token 字段 → 跳过不累加，不报错。
- 异常路径（except）→ 不发 token_usage（数据可能不完整）。

## §2 前端事件类型与数据流

**types.ts**：`AgentEvent.type` 联合类型加 `'token_usage'`。
```ts
type: '...' | 'token_usage'
```

**useWebSocket.ts**：无需改动。现有 event 处理通用——收到 `message.type === 'event'`
就把 `message.event` push 进 streaming message 的 events 数组。token_usage 复用此路径。

**完整数据流**：
```
agent.py yield {event:{type:"token_usage",...}}
  → server.py WS send_json
  → background.ts 转发给 sidepanel
  → useWebSocket.ts: message.type==='event' → events.push(message.event)
  → [DONE] → message 定稿（含 token_usage 在 events 里）
  → MessageBlock 渲染
```

零新通道，复用已跑通的 step/reflection 路径。

## §3 前端渲染（MessageBlock.tsx）

agent 消息渲染分支改动：

1. 从 `message.events` 提取 token_usage 并从 visibleEvents 排除：
   ```tsx
   const tokenUsage = message.events?.find(e => e.type === 'token_usage')?.data
   const visibleEvents = message.events?.filter(
     e => e.type !== 'activity_status' && e.type !== 'token_usage'
   ) || []
   ```
   token_usage 不是工具步骤，不进 ToolStepsPanel。

2. 内容气泡后渲染胶囊：
   ```tsx
   {tokenUsage && typeof tokenUsage.input === 'number'
     && typeof tokenUsage.output === 'number' && (
     <div className="flex justify-start shrink-0">
       <span className="text-[10px] text-muted-foreground px-3 py-1">
         Token: 入 {tokenUsage.input.toLocaleString()} / 出 {tokenUsage.output.toLocaleString()}
       </span>
     </div>
   )}
   ```

**样式**：`text-[10px] text-muted-foreground`（弱化元信息）、`px-3 py-1`（与气泡左缘对齐）、
`flex justify-start`（与 agent 气泡同侧）、`.toLocaleString()`（千分位）。
不引 Badge 组件，纯文字最轻。

**为什么放气泡外**：token 是对话元信息，性质不同于正文；放气泡外可视觉区分，不干扰
ReactMarkdown 渲染。

**类型兜底**：`typeof === 'number'` 判断，防 `Number(undefined)` = `NaN`。

## §4 历史会话与持久化

**无代码改动**。token_usage 作为 AgentEvent 进 events 数组，随 message 被 IndexedDB
序列化存储，重新加载时原样还原。MessageBlock 从 events 里 find 的逻辑对实时和历史消息
一视同仁，历史会话自动获益。

**限制**：本特性上线前的旧会话 events 里无 token_usage，胶囊不显示（预期行为，不回填）。
MessageBlock 的 `tokenUsage &&` 条件优雅降级——旧消息照常显示步骤和内容。

## §5 测试策略

**后端（pytest）**：
新增 `tests/test_agent.py::test_run_yields_token_usage`：
- mock 一个假 reply_stream，产出 2 次 MODEL_CALL_END（input=5000/output=200,
  input=5200/output=150）
- 跑 `run()`，收集所有 yield 的事件
- 断言存在 `type=="token_usage"` 事件，`data.input==10200`、`data.output==350`
- 断言它在 `[DONE]` 之前
- 前置：复用现有 test_agent.py 的 BrowserAgent 构造方式（若有 fixture）

**前端**：
- types.ts：纯类型改动，tsc 编译通过即可。
- useWebSocket.ts：无逻辑改动，无需新测试。
- MessageBlock.tsx：手动验证（项目无 React Testing Library）。

**集成验证（手动）**：
1. `npm run build`（避免 parse_page 的构建产物遗漏覆辙）+ 重启 agent-core
2. 发一条指令，等 Agent 完成
3. 确认 Agent 回复气泡下方出现 `Token: 入 X,XXX / 出 XXX`
4. 数值随对话复杂度合理
5. 历史会话：旧消息无胶囊、新消息有胶囊

## 涉及文件清单

| 文件 | 改动 |
|---|---|
| `agent-core/agent/agent.py` | run() 累加 MODEL_CALL_END token，[DONE] 前 yield token_usage |
| `agent-core/tests/test_agent.py` | 新增 test_run_yields_token_usage |
| `chrome-extension/src/types/index.ts` | AgentEvent.type 加 `'token_usage'` |
| `chrome-extension/src/components/MessageBlock.tsx` | 提取 token_usage，渲染胶囊 |
