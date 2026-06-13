# 新建会话：后端重置上下文

## 背景与现状

Chrome 扩展 sidepanel 顶部有"新建会话"按钮（`entrypoints/sidepanel/App.tsx:81-87`），当前点击只调用 `useWebSocket.clearMessages`（`hooks/useWebSocket.ts:177-182`），**仅清空前端 React state，不通知后端**。

后端（`server.py`）是**全局单例 Agent**（`_agent`，`server.py:24-36`），对话历史累积在 AgentScope 的 `state.context` 里，跨所有 WebSocket 连接共享。前端 `user_message` 载荷只有 `{type, content}`，无任何会话标识。

结果：点击"新建会话"后，下一条用户消息后端仍当作上一轮对话的延续，**上下文不会被重置**。

## 目标

点击"新建会话"按钮后，后端 Agent 进入全新上下文：清空对话历史，换新 `session_id`，后续对话不再受之前轮次影响。

## 非目标（YAGNI）

- 不做多会话并发（按 sessionId 维护多个 Agent 实例）。当前单用户单后端场景，单会话重置足够。
- 不在 `user_message` 中引入 `session_id` 字段。靠"新建会话时彻底停掉旧任务"保证一致性。
- 不持久化"当前会话上下文"到磁盘（历史会话仍由前端 IndexedDB 的 `saveSession` 处理，与本功能无关）。

## 设计

### 后端

#### 1. `agent/agent.py` — 新增 `reset_context()` 方法

顶部需补 `import uuid`（当前未导入）。在 `BrowserAgent` 类内新增：

```python
def reset_context(self) -> None:
    """清空对话历史，开启全新上下文。

    保留 Agent 实例与已注册工具，仅重置会话状态。
    permission_context 保留（用户级工具授权，跨会话有效）。
    """
    if self._agent is not None:
        st = self._agent.state
        st.context.clear()
        st.summary = ""
        st.session_id = uuid.uuid4().hex
        st.cur_iter = 0
        st.tool_context.clear()
        st.tasks_context.clear()
```

清理范围（用户已确认）：
- `context`、`summary`、`cur_iter`：对话历史与压缩摘要、迭代计数 — **清**。
- `tool_context`、`tasks_context`：上一轮工具/任务状态 — **清**（用户确认一并清空）。
- `session_id`：**换新**。
- `permission_context`：**保留**（用户级 `PermissionMode.BYPASS` 等授权跨会话有效）。

#### 2. `server.py` — 消息分发新增 `new_session` 分支

在 `handle_client` 的 `if/elif` 链（`user_message` 与 `stop` 之间）加入。**关键：该分支自己负责停掉旧任务，不依赖前端先发 `stop`**，避免 `stop` 分支 cancel 后不 await 造成的竞态（见下"竞态处理"）：

```python
elif msg_type == "new_session":
    had_running = _current_task is not None and not _current_task.done()
    if had_running:
        _current_task.cancel()
        try:
            await _current_task          # 确保旧任务彻底结束，避免残留 append 污染新上下文
        except BaseException:
            pass
        _current_task = None
        # 旧任务被打断，通知前端关闭遮罩
        await websocket.send(json.dumps({
            "type": "event",
            "event": {"type": "activity_status", "data": {"status": "done"}},
        }))
    agent.reset_context()
    log.info("已新建会话，上下文已重置")
```

`_current_task` 的 `global` 声明已由 `user_message` 分支（`server.py:90`）覆盖整个函数，此处无需重复声明。

#### 3. `browser/protocol.py` — 注册 `new_session`

`MSG_TYPES` 增加：

```python
"new_session",  # SidePanel → Agent：新建会话，重置上下文
```

本设计后端不新增回复类型：流式中途新建会话时复用已有的 `activity_status: done` 事件关遮罩，该事件经现有 `event` 消息流转，无需在 `MSG_TYPES` 中登记（`validate_message` 只校验扩展→Agent 方向）。

### 前端

#### 1. `hooks/useWebSocket.ts` — 改造 `clearMessages`

```ts
const clearMessages = useCallback(() => {
  chrome.runtime.sendMessage({ type: 'new_session' })
  setMessages([])
  streamingRef.current = null
  setIsStreaming(false)
  setError(null)
  setActivityStatus('idle')
}, [])
```

改动：
- 新增发 `{type:'new_session'}` 给 background。
- 新增 `setActivityStatus('idle')`（新建会话=全新状态，活动状态一并归零）。

依赖数组保持 `[]`（无外部依赖）。**不调用 `stopStream`**：停旧任务的职责交给后端 `new_session` 分支，前端只负责清 UI + 发指令，避免与 `stop` 形成双路径。

#### 2. `entrypoints/background.ts` — 转发 `new_session`

在 `chrome.runtime.onMessage` 监听（`background.ts:203-221`）中加一支，转发到 WS 并**乐观关闭遮罩**：

```ts
if (message.type === 'new_session') {
  wsClient.send({ type: 'new_session' })
  if (isStreamingActive) {
    isStreamingActive = false
    sendToContentScript({ action: 'disable_overlay' })
  }
  sendResponse({ received: true })
}
```

## 行为与时序

**空闲状态点新建会话**：前端清 UI + 发 `new_session` → 后端无旧任务，直接 `reset_context`。遮罩本就关闭。

**流式中途点新建会话**：
1. 前端 `clearMessages`：发 `new_session`，清空 messages/streaming/isStreaming/error/activityStatus。
2. background：收到 `new_session`，乐观关遮罩，转发 `{type:'new_session'}` 到 WS。
3. 后端：`new_session` 分支 cancel + await 旧任务（彻底结束），发 `done` 事件（兜底关遮罩），`reset_context` 清空历史。
4. 用户在新会话发消息 → 后端 `state.context` 为空，全新上下文。

**乐观清 UI**：前端不等后端确认即清空，后端 reset 是内存操作几乎不失败。

## 竞态处理（核心）

agentscope 的 `reply_stream` 在执行中会通过 `_handle_incoming_messages` 把消息 append 进 `state.context`。若 `reset_context` 在旧任务仍在 append 时执行，reset 之后旧任务的遗留 append 会污染新上下文。

规避：`new_session` 分支对旧任务做 `cancel()` + `await`（吞掉 `CancelledError` 及其它异常），确保旧任务所有 append 已完成后，再 `reset_context` 清空。`await` 期间阻塞该连接的消息循环是可接受的（单用户、低频操作、旧任务通常很快收敛）。

之所以不沿用"前端先 `stop` 再 `new_session`"：`stop` 分支（`server.py:95-106`）cancel 后不 await 且立即 `_current_task = None`，新 `new_session` 分支拿不到旧 task 引用，无法保证其结束。统一由 `new_session` 分支处理停旧任务，单一路径，无竞态。

## 测试要点

- 空闲点新建会话 → 发消息 → 后端 context 只含本轮，无历史。
- 连续对话 N 轮 → 新建会话 → 新消息，后端 context 不含前 N 轮（日志/断点验证 `state.context` 长度）。
- 流式中途点新建会话 → 旧任务停止、遮罩关闭、UI 清空；新会话首条消息不被旧轮内容污染。
- `session_id` 在每次新建会话后变化（断点或日志确认）。
- `permission_context` 不被清空（仍为 `BYPASS`）。

## 涉及文件

| 文件 | 改动 |
|---|---|
| `agent-core/agent/agent.py` | 补 `import uuid`；新增 `reset_context()` |
| `agent-core/server.py` | `handle_client` 新增 `new_session` 分支 |
| `agent-core/browser/protocol.py` | `MSG_TYPES` 加 `"new_session"` |
| `chrome-extension/src/hooks/useWebSocket.ts` | `clearMessages` 发 `new_session` + 重置 activityStatus |
| `chrome-extension/src/entrypoints/background.ts` | 转发 `new_session` + 乐观关遮罩 |
