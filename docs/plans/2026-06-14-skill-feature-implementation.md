# Skill 功能实现计划

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 为 Agent 增加 Skill 能力——后端用 agentscope `skills_or_loaders` 加载技能，前端在对话框下方加「技能」按钮，选中后以 `/skill <name> ` 填入输入框，由 Agent 自动读取该技能指令执行。

**Architecture:** 后端在 `BrowserAgent.init()` 构造 `Toolkit` 时传入 `skills_or_loaders=[LocalSkillLoader(...)]`；连接握手后 `handle_client` 调用 `agent.list_skills()` 推送 `{type:"skills_list", skills:[...]}` 给前端（一次性，不随会话变）。前端在 `ChatView` 输入框下方加工具栏 + Popover，选中技能填入 `/skill <name> ` 到 textarea。执行阶段完全复用现有 `user_message` 通道——Agent 看到斜杠命令会自动调用内置 `Skill` 工具读取全文指令。

**Tech Stack:** Python 3.11+ / agentscope 2.0.1 / pytest / pytest-asyncio（后端）；WXT + React 19 + TypeScript + Tailwind v4 + lucide-react（前端）。

**Design doc:** `docs/plans/2026-06-14-skill-feature-design.md`

---

## 任务总览

- **后端（Task 1-5）**：配置 → 示例技能 → Toolkit 注册 → list_skills 方法 → 握手推送 + 测试
- **前端（Task 6-10）**：类型补全 → background 转发 → Hook 缓存 → ChatView 按钮/Popover → App 透传
- **收尾（Task 11-12）**：README + 全量验证 + 提交

---

## Task 1: 后端配置支持多目录 skills

**Files:**
- Modify: `agent-core/config.yaml`
- Modify: `agent-core/tests/test_config_loader.py`（末尾追加）

**Step 1: 修改 config.yaml**

在 `agent-core/config.yaml` 末尾（`server:` 段之后）追加：

```yaml
skills:
  dirs:
    - "./skills"
```

**Step 2: 写失败测试**

在 `agent-core/tests/test_config_loader.py` 末尾追加：

```python
def test_skills_config_has_default_dir():
    """config.yaml 应包含 skills.dirs，默认含 ./skills。"""
    from config_loader import load_config
    config = load_config("config.yaml")
    assert "skills" in config
    assert "./skills" in config["skills"]["dirs"]
```

**Step 3: 运行测试，预期通过**

Run: `cd agent-core && uv run pytest tests/test_config_loader.py::test_skills_config_has_default_dir -v`
Expected: PASS（config.yaml 已改）

**Step 4: 提交**

```bash
cd agent-core
git add config.yaml tests/test_config_loader.py
git commit -m "feat: config.yaml 新增 skills.dirs 多目录配置"
```

---

## Task 2: 创建内置示例技能

**Files:**
- Create: `agent-core/skills/example/SKILL.md`

**Step 1: 创建示例技能文件**

创建 `agent-core/skills/example/SKILL.md`：

```markdown
---
name: example
description: 一个示例技能，演示如何编写和使用 Skill
---

# 示例技能

这是一个示例技能。当用户在输入框输入 `/skill example` 时，Agent 会通过内置的 `Skill` 工具读取本文件，然后按这里的指令操作。

## 使用方式

1. 确认用户的具体需求
2. 按需调用浏览器工具（parse_dom / click / input_text 等）完成任务
3. 完成后用 done 工具汇报结果

## 自定义技能

在 `agent-core/skills/<你的技能名>/SKILL.md` 创建新技能即可。frontmatter 必须包含 `name` 和 `description` 两个字段，正文是给 Agent 看的指令（markdown）。
```

**Step 2: 验证 frontmatter 可被解析**

Run（在 agent-core 目录）：
```bash
cd agent-core
uv run python -c "
import asyncio
from agentscope.skill import LocalSkillLoader

async def main():
    loader = LocalSkillLoader(directory='./skills', scan_subdir=True)
    skills = await loader.list_skills()
    print('加载到技能:', [s.name for s in skills])
    assert any(s.name == 'example' for s in skills), 'example 技能未加载'
    print('OK')

asyncio.run(main())
"
```
Expected: 输出 `加载到技能: ['example']` 和 `OK`

> **关键**：必须传 `scan_subdir=True`，否则只扫描 `./skills/SKILL.md` 不会进 `example/` 子目录。

**Step 3: 提交**

```bash
cd agent-core
git add skills/
git commit -m "feat: 新增 example 示例技能 SKILL.md"
```

---

## Task 3: BrowserAgent.init() 注册技能 + list_skills 方法

**Files:**
- Modify: `agent-core/agent/agent.py`（`init()` 方法第 53-82 行；新增 `list_skills` 方法）
- Modify: `agent-core/tests/test_agent.py`（追加测试）

**Step 1: 写失败测试**

在 `agent-core/tests/test_agent.py` 的 `_make_config()` 函数里给 config 增加 `skills` 段，使所有现有测试都能正常初始化：

```python
def _make_config():
    return {
        "llm": {"provider": "dashscope", "model": "qwen-plus", "api_key": "test-key"},
        "vlm": {"provider": "dashscope", "model": "qwen-plus", "api_key": "test-key"},
        "skills": {"dirs": ["./skills"]},
    }
```

在文件末尾追加：

```python
@pytest.mark.asyncio
async def test_list_skills_returns_example():
    """init 后 list_skills 应返回 [{name, description}]，含 example。"""
    agent = BrowserAgent(_make_config())
    agent.init()
    skills = await agent.list_skills()
    names = [s["name"] for s in skills]
    assert "example" in names
    example = next(s for s in skills if s["name"] == "example")
    assert "description" in example
    assert isinstance(example["description"], str)


@pytest.mark.asyncio
async def test_list_skills_empty_when_no_dirs():
    """skills.dirs 为空时 list_skills 返回空列表，不报错。"""
    config = _make_config()
    config["skills"] = {"dirs": []}
    agent = BrowserAgent(config)
    agent.init()
    skills = await agent.list_skills()
    assert skills == []
```

**Step 2: 运行测试，预期失败**

Run: `cd agent-core && uv run pytest tests/test_agent.py::test_list_skills_returns_example -v`
Expected: FAIL — `AttributeError: 'BrowserAgent' object has no attribute 'list_skills'`

**Step 3: 修改 agent.py — 在 import 区加 os 和 LocalSkillLoader**

在 `agent-core/agent/agent.py` 顶部 import 区（第 7-21 行附近），把：

```python
import json
import re
```

改成：

```python
import json
import os
import re
```

并在 toolkit 导入行（第 11 行）：

```python
from agentscope.tool import Toolkit, FunctionTool
```

下面新增一行：

```python
from agentscope.skill import LocalSkillLoader
```

**Step 4: 修改 agent.py — init() 注册技能**

把 `init()` 里的这段（第 64-69 行）：

```python
        # 创建并注册浏览器工具
        tool_functions = create_browser_tools(
            self._conn, vlm_model, self._viewport_info,
        )
        tool_objects = [FunctionTool(fn) for fn in tool_functions.values()]
        toolkit = Toolkit(tools=tool_objects)
```

替换为：

```python
        # 创建并注册浏览器工具
        tool_functions = create_browser_tools(
            self._conn, vlm_model, self._viewport_info,
        )
        tool_objects = [FunctionTool(fn) for fn in tool_functions.values()]

        # 注册技能：从配置的多目录扫描 SKILL.md（递归子目录）。
        # scan_subdir=True：每个技能位于 <dir>/<skill-name>/SKILL.md。
        skill_dirs = self._config.get("skills", {}).get("dirs", [])
        skills_or_loaders = []
        for d in skill_dirs:
            if os.path.isdir(d):
                skills_or_loaders.append(
                    LocalSkillLoader(directory=d, scan_subdir=True)
                )
            else:
                log.warning("技能目录不存在，已跳过: %s", d)

        toolkit = Toolkit(
            tools=tool_objects,
            skills_or_loaders=skills_or_loaders,
        )
```

**Step 5: 新增 list_skills 方法**

在 `agent.py` 的 `init()` 方法之后（第 82 行 `log.info("BrowserAgent 初始化完成...")` 之后、`def reset_context` 之前）插入：

```python
    async def list_skills(self) -> list[dict]:
        """返回当前注册的技能清单 [{name, description}]，供前端展示。

        直接委托给 toolkit，技能集是全局静态的，与会话无关。
        """
        if self._agent is None:
            return []
        skills = await self._agent.toolkit._get_available_skills()
        return [
            {"name": s.name, "description": s.description}
            for s in skills.values()
        ]

```

**Step 6: 运行全部 agent 测试，预期通过**

Run: `cd agent-core && uv run pytest tests/test_agent.py -v`
Expected: 全部 PASS（含新加的 2 个 list_skills 测试 + 原有测试）

> ⚠️ 若原测试 `test_agent_init` 等因 config 缺 skills 段失败，确认 `_make_config()` 已按 Step 1 加上 `skills` 段。

**Step 7: 提交**

```bash
cd agent-core
git add agent/agent.py tests/test_agent.py
git commit -m "feat: BrowserAgent 注册技能并暴露 list_skills 方法"
```

---

## Task 4: server 握手后推送 skills_list

**Files:**
- Modify: `agent-core/server.py`（`handle_client` 第 59-65 行附近）
- Modify: `agent-core/tests/test_server.py`（追加测试）

**Step 1: 写失败测试**

在 `agent-core/tests/test_server.py` 末尾追加：

```python
@pytest.mark.asyncio
async def test_skills_list_pushed_on_connect():
    """连接握手后应推送 {type: skills_list, skills: [...]}。"""
    import server

    agent = _mock_agent()

    async def _fake_list_skills():
        return [{"name": "example", "description": "示例"}]

    agent.list_skills = _fake_list_skills
    server._agent = agent
    server._current_task = None

    try:
        # 空消息列表：连接后立即结束（触发握手推送）
        ws = FakeWS([])
        await server.handle_client(ws, {})

        skills_msgs = [json.loads(s) for s in ws.sent if json.loads(s).get("type") == "skills_list"]
        assert len(skills_msgs) == 1
        assert skills_msgs[0]["skills"] == [{"name": "example", "description": "示例"}]
    finally:
        server._agent = None
        server._current_task = None
```

**Step 2: 运行测试，预期失败**

Run: `cd agent-core && uv run pytest tests/test_server.py::test_skills_list_pushed_on_connect -v`
Expected: FAIL — `assert len(skills_msgs) == 1`（当前未推送，列表为空）

**Step 3: 修改 server.py — 在 attach_ws 后推送技能列表**

在 `agent-core/server.py` 的 `handle_client` 函数里，把这段（第 59-65 行）：

```python
    agent = _get_or_create_agent(config)
    agent.attach_ws(websocket)

    # 重连时通知前端之前的状态已丢失
    if agent._busy:
        log.warning("重连时 Agent 仍在执行，前端可能需要刷新状态")
```

替换为：

```python
    agent = _get_or_create_agent(config)
    agent.attach_ws(websocket)

    # 握手后推送一次技能清单（技能是全局静态能力，与会话无关）。
    # 失败不阻断连接——前端 skills 保持空，按钮仍可点（显示空列表）。
    try:
        skills = await agent.list_skills()
        await websocket.send(json.dumps({"type": "skills_list", "skills": skills}))
        log.info("已推送技能清单，共 %d 个技能", len(skills))
    except Exception as e:
        log.warning("推送技能列表失败: %s", e)

    # 重连时通知前端之前的状态已丢失
    if agent._busy:
        log.warning("重连时 Agent 仍在执行，前端可能需要刷新状态")
```

**Step 4: 运行测试，预期通过**

Run: `cd agent-core && uv run pytest tests/test_server.py -v`
Expected: 全部 PASS（含新测试 + 原 new_session 测试）

**Step 5: 运行后端全量测试**

Run: `cd agent-core && uv run pytest -v`
Expected: 全部 PASS

**Step 6: 提交**

```bash
cd agent-core
git add server.py tests/test_server.py
git commit -m "feat: server 连接握手后推送 skills_list 技能清单"
```

---

## Task 5: 后端手动验证（端到端冒烟）

**Files:** 无（仅运行验证）

**Step 1: 启动后端，观察日志**

Run（确保 `.env` 已配好 LLM/VLM key）：
```bash
cd agent-core
uv run python server.py
```
Expected: 日志出现 `已推送技能清单，共 1 个技能`（当有 Chrome 扩展连接时）

> 若无扩展连接，可用 wscat 手动验证：另开终端 `npx wscat -c ws://localhost:8765`，连接后应立即收到 `{"type":"skills_list","skills":[{"name":"example","description":"..."}]}`。

**Step 2: 停止后端**

Ctrl+C 停止。

> 无需提交（仅验证）。

---

## Task 6: 前端类型补全

**Files:**
- Modify: `chrome-extension/src/types/index.ts`

**Step 1: 修改 types/index.ts**

把 `chrome-extension/src/types/index.ts` 第 1-14 行的：

```typescript
/** 侧边面板 → 后台的消息 */
export interface SidepanelMessage {
  type: 'user_message' | 'get_status'
  content?: string
}

/** 后台 → 侧边面板的消息 */
export interface BackgroundMessage {
  type: 'stream' | 'error' | 'status_update' | 'event'
  content?: string
  status?: 'connected' | 'disconnected'
  event?: AgentEvent
  error?: string
}
```

替换为：

```typescript
/** 侧边面板 → 后台的消息 */
export interface SidepanelMessage {
  type: 'user_message' | 'get_status' | 'stop' | 'new_session'
  content?: string
}

/** 后台 → 侧边面板的消息 */
export interface BackgroundMessage {
  type: 'stream' | 'error' | 'status_update' | 'event' | 'skills_list'
  content?: string
  status?: 'connected' | 'disconnected'
  event?: AgentEvent
  error?: string
  skills?: SkillInfo[]
}

/** 技能信息（后端推送的技能清单元素） */
export interface SkillInfo {
  name: string
  description: string
}
```

> 说明：`SidepanelMessage` 顺带补全了实际已在使用但类型未声明的 `stop` / `new_session`（`useWebSocket.ts` 第 174、179 行已发送），消除既有类型漂移。

**Step 2: 验证类型检查**

Run: `cd chrome-extension && npx tsc --noEmit`
Expected: 无新增错误（若 wxt 类型生成报错，先 `npm run postinstall` 即 `wxt prepare`）

**Step 3: 提交**

```bash
cd chrome-extension
git add src/types/index.ts
git commit -m "feat(types): 补全 SidepanelMessage，新增 skills_list 和 SkillInfo 类型"
```

---

## Task 7: background 转发 skills_list 消息

**Files:**
- Modify: `chrome-extension/src/entrypoints/background.ts`（第 26-56 行 WS 消息路由）

**Step 1: 修改 background.ts 的 WS 路由**

在 `chrome-extension/src/entrypoints/background.ts` 的 `wsClient.onMessage` 回调里，找到 `error` 分支（约第 48-55 行）：

```typescript
    } else if (type === 'error') {
      // 出错时也关闭遮罩
      if (isStreamingActive) {
        isStreamingActive = false
        sendToContentScript({ action: 'disable_overlay' })
      }
      chrome.runtime.sendMessage(msg).catch(() => {})
    }
```

在 `}` 之前（即 `error` 分支的 `chrome.runtime.sendMessage(msg).catch(() => {})` 之后、闭合 `}` 之前）新增一个 `else if` 分支：

```typescript
    } else if (type === 'skills_list') {
      // 转发后端推送的技能清单到 sidepanel
      chrome.runtime.sendMessage(msg).catch(() => {})
    }
```

修改后该段应为：

```typescript
    } else if (type === 'error') {
      // 出错时也关闭遮罩
      if (isStreamingActive) {
        isStreamingActive = false
        sendToContentScript({ action: 'disable_overlay' })
      }
      chrome.runtime.sendMessage(msg).catch(() => {})
    } else if (type === 'skills_list') {
      // 转发后端推送的技能清单到 sidepanel
      chrome.runtime.sendMessage(msg).catch(() => {})
    }
```

**Step 2: 验证构建**

Run: `cd chrome-extension && npm run build`
Expected: BUILD 成功，无类型错误

**Step 3: 提交**

```bash
cd chrome-extension
git add src/entrypoints/background.ts
git commit -m "feat(background): 转发 skills_list 消息到 sidepanel"
```

---

## Task 8: useWebSocket 缓存技能列表

**Files:**
- Modify: `chrome-extension/src/hooks/useWebSocket.ts`

**Step 1: 修改 useWebSocket.ts**

a) 在 import 行（第 2 行）的类型导入加 `SkillInfo`：

```typescript
import type { AgentEvent, ActivityStatus, BackgroundMessage, Message, SkillInfo } from '@/types'
```

b) 在 `UseWebSocketReturn` 接口（第 4-13 行）末尾加 `skills`：

```typescript
export interface UseWebSocketReturn {
  status: 'connected' | 'disconnected'
  sendTask: (content: string) => void
  messages: Message[]
  isStreaming: boolean
  stopStream: () => void
  error: string | null
  clearMessages: () => void
  activityStatus: ActivityStatus
  skills: SkillInfo[]
}
```

c) 在 state 声明区（第 24 行 `useState<ActivityStatus>('idle')` 之后）新增：

```typescript
  const [skills, setSkills] = useState<SkillInfo[]>([])
```

d) 在 listener 的消息处理里，`status_update` 分支之后（第 109 行之后）新增分支：

```typescript
      if (message.type === 'skills_list') {
        setSkills(message.skills ?? [])
      }
```

e) 在最后的 return（第 187 行）加 `skills`：

```typescript
  return { status, sendTask, messages, isStreaming, stopStream, error, clearMessages, activityStatus, skills }
```

**Step 2: 验证构建**

Run: `cd chrome-extension && npm run build`
Expected: BUILD 成功

**Step 3: 提交**

```bash
cd chrome-extension
git add src/hooks/useWebSocket.ts
git commit -m "feat(hooks): useWebSocket 缓存 skills_list 推送的技能清单"
```

---

## Task 9: ChatView 技能按钮 + Popover

**Files:**
- Modify: `chrome-extension/src/components/ChatView.tsx`

**Step 1: 修改 ChatView 的 import**

把 `chrome-extension/src/components/ChatView.tsx` 第 1 行的：

```typescript
import { Send, Square } from 'lucide-react'
```

替换为：

```typescript
import { Send, Square, Sparkles } from 'lucide-react'
```

把第 5 行的：

```typescript
import type { Message } from '@/types'
```

替换为：

```typescript
import type { Message, SkillInfo } from '@/types'
```

**Step 2: 修改 ChatViewProps 和组件签名**

把第 16-24 行的：

```typescript
interface ChatViewProps {
  messages: Message[]
  isStreaming: boolean
  sendTask: (content: string) => void
  stopStream: () => void
  activityStatus: string
}

export function ChatView({ messages, isStreaming, sendTask, stopStream, activityStatus }: ChatViewProps) {
  const [inputValue, setInputValue] = useState('')
  const scrollRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
```

替换为：

```typescript
interface ChatViewProps {
  messages: Message[]
  isStreaming: boolean
  sendTask: (content: string) => void
  stopStream: () => void
  activityStatus: string
  skills: SkillInfo[]
}

export function ChatView({ messages, isStreaming, sendTask, stopStream, activityStatus, skills }: ChatViewProps) {
  const [inputValue, setInputValue] = useState('')
  const [showSkills, setShowSkills] = useState(false)
  const scrollRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const skillPopoverRef = useRef<HTMLDivElement>(null)

  // 点击 Popover 外部时关闭
  useEffect(() => {
    if (!showSkills) return
    const handler = (e: MouseEvent) => {
      if (skillPopoverRef.current && !skillPopoverRef.current.contains(e.target as Node)) {
        setShowSkills(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [showSkills])

  // 选中技能：把 /skill <name> 填入输入框（保留用户已输入内容），聚焦并把光标置于末尾
  const insertSkill = useCallback((skillName: string) => {
    const prefix = `/skill ${skillName} `
    setInputValue((prev) => {
      const trimmed = prev.trim()
      return trimmed ? `${prefix}${trimmed}` : prefix
    })
    setShowSkills(false)
    // 聚焦并移到末尾（下一帧，确保 value 已更新）
    requestAnimationFrame(() => {
      const ta = textareaRef.current
      if (ta) {
        ta.focus()
        const end = ta.value.length
        ta.setSelectionRange(end, end)
      }
    })
  }, [])
```

**Step 3: 在输入框下方加技能工具栏**

把 `<footer>` 里的 `</InputGroup>` 之后、`</footer>` 之前（第 104-105 行）：

```typescript
        </InputGroup>
      </footer>
```

替换为：

```typescript
        </InputGroup>

        {/* 技能工具栏 */}
        <div ref={skillPopoverRef} className="relative mt-2">
          <Button
            variant="outline"
            size="sm"
            className="h-7 text-xs"
            onClick={() => setShowSkills((v) => !v)}
            disabled={isStreaming}
            title="选择技能"
          >
            <Sparkles className="size-3.5" />
            技能
          </Button>
          {showSkills && (
            <div className="absolute bottom-full mb-2 left-0 w-72 rounded-md border bg-popover p-1 shadow-md z-10">
              {skills.length === 0 ? (
                <div className="px-3 py-2 text-xs text-muted-foreground">暂无可用技能</div>
              ) : (
                skills.map((s) => (
                  <button
                    key={s.name}
                    type="button"
                    className="block w-full text-left px-3 py-2 rounded-sm hover:bg-accent"
                    onClick={() => insertSkill(s.name)}
                  >
                    <div className="text-xs font-medium">/skill {s.name}</div>
                    <div className="text-[11px] text-muted-foreground line-clamp-1">{s.description}</div>
                  </button>
                ))
              )}
            </div>
          )}
        </div>
      </footer>
```

**Step 4: 验证构建**

Run: `cd chrome-extension && npm run build`
Expected: BUILD 成功

> 注意：`bg-popover` 是 shadcn/Tailwind 默认 token。若该 class 未定义（构建时不会报错，只是视觉无背景色），后续可在 `assets/index.css` 里定义 `--popover` 变量。这一步先用 `bg-popover`，若实测发现无样式可退回 `bg-background` 或 `bg-card`。

**Step 5: 提交**

```bash
cd chrome-extension
git add src/components/ChatView.tsx
git commit -m "feat(ChatView): 输入框下方新增技能按钮与 Popover，选中填入斜杠命令"
```

---

## Task 10: App 透传 skills 到 ChatView

**Files:**
- Modify: `chrome-extension/src/entrypoints/sidepanel/App.tsx`

**Step 1: 修改 App.tsx 的 useWebSocket 解构**

把 `chrome-extension/src/entrypoints/sidepanel/App.tsx` 第 12 行的：

```typescript
  const { status, sendTask, messages, isStreaming, stopStream, clearMessages, activityStatus } = useWebSocket()
```

替换为：

```typescript
  const { status, sendTask, messages, isStreaming, stopStream, clearMessages, activityStatus, skills } = useWebSocket()
```

**Step 2: 修改 ChatView 调用，传入 skills**

把第 95 行的：

```tsx
      <ChatView messages={messages} isStreaming={isStreaming} sendTask={sendTask} stopStream={stopStream} activityStatus={activityStatus} />
```

替换为：

```tsx
      <ChatView messages={messages} isStreaming={isStreaming} sendTask={sendTask} stopStream={stopStream} activityStatus={activityStatus} skills={skills} />
```

**Step 3: 验证构建**

Run: `cd chrome-extension && npm run build`
Expected: BUILD 成功，产物在 `.output/chrome-mv3/`

**Step 4: 提交**

```bash
cd chrome-extension
git add src/entrypoints/sidepanel/App.tsx
git commit -m "feat(App): 透传 skills 到 ChatView"
```

---

## Task 11: README 补充技能说明

**Files:**
- Modify: `README.md`

**Step 1: 在 README 的「使用」节末尾（第 72 行「新建会话」段之后）追加技能说明**

在第 72 行 `**新建会话**：...` 段之后，`## 配置` 之前，新增：

```markdown

**技能（Skill）**：SidePanel 输入框下方有一个「✦ 技能」按钮。点击会弹出当前可用技能列表（名称 + 描述），选中某项后会在输入框填入 `/skill <技能名> `（光标停在末尾），你可以补充具体任务再发送。Agent 会自动读取该技能的完整指令并按其执行。

技能是一份 `SKILL.md` 指令文档（带 YAML frontmatter 的 `name`/`description` + markdown 正文）。后端默认从 `agent-core/skills/` 目录加载（递归扫描子目录），可在 `agent-core/config.yaml` 的 `skills.dirs` 追加更多目录：

```yaml
skills:
  dirs:
    - "./skills"
    - "/path/to/your/skills"   # 自定义目录
```

新增技能：在已配置的目录下创建 `<技能名>/SKILL.md`，重启后端即可。示例见 `agent-core/skills/example/SKILL.md`。
```

**Step 2: 提交**

```bash
cd /Users/heren/code/BU-Agent-Extension
git add README.md
git commit -m "docs: README 补充 Skill 功能说明"
```

---

## Task 12: 全量验证

**Files:** 无（仅运行验证）

**Step 1: 后端全量测试**

Run: `cd agent-core && uv run pytest -v`
Expected: 全部 PASS

**Step 2: 前端构建**

Run: `cd chrome-extension && npm run build`
Expected: BUILD 成功

**Step 3: 端到端手动验证清单**

启动后端 `cd agent-core && uv run python server.py`，Chrome 加载 `chrome-extension/.output/chrome-mv3/`，打开 SidePanel，逐项验证：

- [ ] 连接后输入框下方出现「✦ 技能」按钮
- [ ] 点击按钮弹出 Popover，列出 `example` 技能（名称 `/skill example` + 描述）
- [ ] 点击 `example`，输入框变为 `/skill example ` 且光标聚焦在末尾
- [ ] 在输入框已有内容时点技能，斜杠命令插在前面（如 `/skill example 原内容`）
- [ ] Popover 打开时点击空白处，Popover 关闭
- [ ] Agent 流式输出（isStreaming）时技能按钮禁用
- [ ] 输入 `/skill example 你好` 发送，Agent 能调用内置 Skill 工具读取技能并回复

**Step 4: 验收完成，无需额外提交**（前面各 Task 已逐个提交）

---

## 验证完成的标志

- 后端 `pytest -v` 全绿
- 前端 `npm run build` 成功
- 手动验证清单全部勾选
- `git log --oneline` 显示 11 个 feat/docs 提交（Task 1-11，Task 5/12 无提交）

## 回滚说明

每个 Task 独立提交，若某步出问题可 `git revert <commit>` 单独回退。后端改动集中在 `agent.py`/`server.py`/`config.yaml`，前端集中在 `ChatView.tsx`/`App.tsx`/`useWebSocket.ts`/`background.ts`/`types/index.ts`，无跨模块强耦合。
