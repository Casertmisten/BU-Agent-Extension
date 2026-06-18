# Skill 功能设计

- 日期：2026-06-14
- 状态：已确认，待生成实现计划
- 范围：agent-core（后端）+ chrome-extension（前端）

## 目标

为 Agent 增加 Skill（技能）能力：后端直接使用 agentscope v2 的 Skill 机制加载技能指令文档；前端在对话框下方新增一个「技能」按钮，点击弹出技能列表，选中后以斜杠命令格式 `/skill <name> ` 填入输入框（不自动发送），由 Agent 自行读取该技能指令并执行。

## 背景与现状

### 后端（agent-core, agentscope 2.0.1）

- `BrowserAgent`（`agent/agent.py`）以组合方式封装 agentscope `Agent`，当前构造 `Toolkit(tools=...)` **只传了工具，未使用 Skill**。
- agentscope 的 Skill 是「指令包」而非可调用工具：一份带 YAML frontmatter（`name` / `description`）的 `SKILL.md` 文档。
- 注册方式：`Toolkit(skills_or_loaders=[...])`，元素可为目录字符串 / `Skill` 对象 / `SkillLoaderBase` 实例。框架自动：
  1. 把技能 `name`/`description`/`dir` 注入系统提示词（`<agent-skills>` 块）；
  2. 当至少有一个技能时，挂载内置 `Skill` 工具（`SkillViewer`，工具名固定为 `Skill`）。
- Agent 运行时通过调用 `Skill(skill="<name>")` 工具按需读取技能全文 markdown，再按指令使用真正的工具。
- `Toolkit._get_available_skills(groups=None) -> dict[str, Skill]`（async）是获取当前技能清单的入口。

### 前端（chrome-extension, WXT + React + Tailwind）

- 输入区在 `ChatView.tsx` 的 `<footer>` 里，是一个 `<InputGroup>` 内含 `<InputGroupTextarea>` 和右下角的发送/停止按钮。
- 消息发送：`useWebSocket` 的 `sendTask(content)` → `chrome.runtime.sendMessage({type:'user_message', content})` → `background.ts` → `wsClient.send(...)` → 后端。
- `types/index.ts` 的 `SidepanelMessage` 类型已落后（漏声明 `stop` / `new_session`），需一并补全。
- 后端→前端：`background.ts` 通用转发 `wsClient.onMessage → chrome.runtime.sendMessage`。

## 关键决策（已与用户确认）

1. **交互**：弹出技能列表 → 选择 → 把 `/skill <name> ` 填入输入框（不自动发送），用户可补写任务后手动发送。
2. **技能列表数据源**：后端推送。
3. **技能加载**：可配置多目录聚合。
4. **填入格式**：斜杠命令 `/skill <name> `。
5. **推送时机**：WebSocket 连接握手后推送一次；`new_session` 时不重推（技能是全局静态能力，与会话无关）。
6. **UI 形态**：输入框下方新增紧凑工具栏 + 一个「✦ 技能」按钮；点击弹出 Popover 气泡列出技能。

## 架构与数据流

```
┌──────────────── chrome-extension ────────────────┐        ┌──────── agent-core ────────┐
│  ChatView (footer)                               │        │  BrowserAgent              │
│  ┌────────────────────────────┐                  │        │   └─ Agent (agentscope)    │
│  │ textarea        [发送 ➤]   │                  │        │       └─ Toolkit           │
│  └────────────────────────────┘                  │        │           ├─ tools          │
│  ┌────────────────────────────┐                  │        │           └─ skills ← 新增  │
│  │ ✦ 技能  [popover: skill-A] │ ← 新增           │        │                (多目录扫描)  │
│  └────────────────────────────┘                  │        │                            │
│         │ 选 skill-A → 填入 /skill skill-A <光标>│        │  server.handle_client      │
└──────────────────────────────────────────────────┘        │   ① 连接后推送 skills_list │
            │ user_message: "/skill skill-A ..."            │   ② user_message 原样跑    │
            └──────WebSocket ws://8765 ───────────────────►│                            │
                                                              │ Agent 调用内置 Skill 工具   │
                                                              │ 读取 skill-A 全文指令并执行 │
```

**数据流要点**：

1. **加载（启动时）**：`init()` 从配置的多目录加载 `skills_or_loaders`，框架扫描每个目录下的 `SKILL.md`。
2. **推送（握手后一次）**：`handle_client` 在 `attach_ws` 后调用 `agent.list_skills()` 拿 `[{name, description}]`，推 `{type:"skills_list", skills:[...]}`。
3. **选择填入**：popover 点击 → textarea 填 `/skill <name> ` 并聚焦。
4. **执行（无新协议）**：发送的是普通 `user_message`；Agent 识别斜杠命令后调用内置 `Skill` 工具读取全文并执行，完全走现有 `run()` 流程。

## 后端设计（agent-core）

### 配置：多目录（`config.yaml` + `config_loader.py`）

`config.yaml` 新增：

```yaml
skills:
  dirs:
    - "./skills"          # 内置示例技能目录
    # 用户可追加更多目录
```

`config_loader.py` 读取时给默认值 `["./skills"]`，路径相对 `agent-core/` 工作目录解析。

### `BrowserAgent.init()` 注册技能（`agent/agent.py`）

构造 `Toolkit` 时传入 `skills_or_loaders`：

```python
from agentscope.skill import LocalSkillLoader

# scan_subdir=True：每个技能放在 <dir>/<skill-name>/SKILL.md，需递归扫描子目录
skill_dirs = self._config.get("skills", {}).get("dirs", ["./skills"])
skills_or_loaders = [
    LocalSkillLoader(directory=d, scan_subdir=True)
    for d in skill_dirs if os.path.isdir(d)
]

toolkit = Toolkit(
    tools=tool_objects,
    skills_or_loaders=skills_or_loaders,
)
```

> **关键**：`LocalSkillLoader(directory=..., scan_subdir=False)`（默认）只扫描目录自身的 `SKILL.md`，不进子目录。示例技能放在 `skills/example/SKILL.md`，因此**必须传 `scan_subdir=True`** 才能被发现。

用显式 `LocalSkillLoader`（而非直接传 str）便于跳过不存在的目录并记录警告。`reset_context()` 复用旧 `toolkit`，无需改。

### 暴露技能列表查询（`agent/agent.py`）

```python
async def list_skills(self) -> list[dict]:
    """返回 [{name, description}]，供前端展示。"""
    skills = await self._agent.toolkit._get_available_skills()
    return [{"name": s.name, "description": s.description} for s in skills.values()]
```

### 握手推送（`server.py`）

在 `attach_ws` 之后、消息循环之前插入：

```python
agent.attach_ws(websocket)
try:
    skills = await agent.list_skills()
    await websocket.send(json.dumps({"type": "skills_list", "skills": skills}))
except Exception as e:
    log.warning("推送技能列表失败: %s", e)
```

### 内置示例技能（`agent-core/skills/example/SKILL.md`）

```markdown
---
name: example
description: 一个示例技能，演示如何编写和使用 Skill
---
# 示例技能

这是一个示例技能。当用户在输入框输入 `/skill example` 时，Agent 会通过内置的 `Skill` 工具读取本文件，然后按这里的指令操作。

## 使用方式
1. 确认用户的具体需求
2. 按需调用浏览器工具完成任务
3. 汇报结果
```

## 前端设计（chrome-extension）

### 协议类型补全（`src/types/index.ts`）

```typescript
export interface BackgroundMessage {
  type: 'stream' | 'error' | 'status_update' | 'event' | 'skills_list'
  content?: string
  status?: 'connected' | 'disconnected'
  event?: AgentEvent
  error?: string
  skills?: SkillInfo[]            // 新增
}

export interface SkillInfo {
  name: string
  description: string
}

// 顺带补全之前漏声明的
export interface SidepanelMessage {
  type: 'user_message' | 'get_status' | 'stop' | 'new_session'
  content?: string
}
```

### WebSocket Hook 缓存技能（`src/hooks/useWebSocket.ts`）

```typescript
const [skills, setSkills] = useState<SkillInfo[]>([])

// onMessage 新增分支
case 'skills_list':
  setSkills(msg.skills ?? [])
  break

return { ..., skills }
```

### background 转发（`src/entrypoints/background.ts`）

`background.ts` 的 WS 转发是**显式 if-else 链**（`action`/`stream`/`event`/`error`），**不是通用透传**，因此**必须新增 `skills_list` 转发分支**：

```typescript
} else if (type === 'skills_list') {
  chrome.runtime.sendMessage(msg).catch(() => {})
}
```

### 技能按钮 + Popover（`src/components/ChatView.tsx`）

`ChatView` 新增 props `skills: SkillInfo[]`。在 `<InputGroup>` 之后加工具栏 + popover：

```tsx
<div className="relative mt-2">
  <Button variant="outline" size="sm" onClick={() => setShowSkills(v => !v)} disabled={isStreaming}>
    <Sparkles className="size-3.5" /> 技能
  </Button>
  {showSkills && (
    <div className="absolute bottom-full mb-2 left-0 w-72 rounded-md border bg-popover shadow-md z-10">
      {skills.length === 0 ? (
        <div className="p-3 text-xs text-muted-foreground">暂无可用技能</div>
      ) : skills.map(s => (
        <button key={s.name} className="block w-full text-left px-3 py-2 hover:bg-accent"
          onClick={() => { insertSkill(s.name); setShowSkills(false) }}>
          <div className="text-xs font-medium">/skill {s.name}</div>
          <div className="text-[11px] text-muted-foreground line-clamp-1">{s.description}</div>
        </button>
      ))}
    </div>
  )}
</div>
```

`insertSkill(name)`：把 textarea 设为 `/skill <name> `（若已有内容则在行首插入并加空格分隔），然后 `textareaRef.current?.focus()`。

### App 透传（`src/entrypoints/sidepanel/App.tsx`）

`useWebSocket()` 解构 `skills`，作为 prop 传给 `<ChatView skills={skills} ... />`。

## 错误处理与边界

- **技能目录为空/不存在**：`list_skills()` 返回 `[]`，前端 popover 显示「暂无可用技能」；`Toolkit` 不挂 `Skill` 工具，Agent 也不识别斜杠命令——合理降级，不报错。
- **用户手动输入不存在的 `/skill xxx`**：Agent 调用 `Skill` 工具时框架返回「未找到该技能」，经现有 `TOOL_RESULT_END` 流程显示为步骤失败卡片，Agent 自行告知用户。
- **握手推送失败**：`server.py` 里 try/except 包住，记 warning 不阻断连接；前端 `skills` 保持 `[]`，按钮仍可点。

## 测试策略

| 层 | 测试 |
|----|------|
| 后端单元 | `test_skills_loading`：init 后 `list_skills()` 返回示例技能 |
| 后端集成 | `test_skills_list_push`：连接后 WS 收到 `skills_list`，格式正确 |
| 后端集成 | 发 `/skill example ...` 验证 Agent 能调用 Skill 工具（mock LLM 断言 tool_call） |
| 前端 | 手动验证：连接后技能按钮可点、popover 列出技能、点击填入 `/skill xxx ` 且光标聚焦 |
| 文档 | README 补充技能使用说明 |

## 不做（YAGNI）

- 不做技能的新增/编辑/删除 UI（用户直接改 `skills/` 目录文件即可）。
- 不做技能分组（`tool_groups`）激活/停用——当前只有默认 `basic` 组。
- 不做远程/数据库技能加载器（`SkillLoaderBase` 自定义子类）。
- 不做技能热重载（运行期改文件不实时刷新，需重启）。
- 不为前端引入测试框架（与项目现状一致，靠手动 + 后端测试）。
