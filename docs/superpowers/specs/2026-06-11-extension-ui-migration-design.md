# Extension UI 全套技术栈迁移设计

> 方案 B：全新项目替换 — 将 chrome-extension 从原生 JS 迁移到 React + WXT + Tailwind v4 + shadcn/ui

## 1. 背景

当前 `chrome-extension/` 使用原生 JavaScript + 内联 CSS（~850 行），功能包括聊天视图、WebSocket 通信、content script DOM 操作。参考项目 `ui参考/` 提供了一套成熟的 React + WXT + shadcn/ui 扩展 UI，包含事件卡片系统、历史记录、配置面板等完整功能。

目标：复用参考项目的全套技术栈和交互模式，全新替换现有前端，保留 WebSocket 通信架构和 content.js 不变。

## 2. 项目结构

```
chrome-extension/
├── wxt.config.ts              # WXT 构建配置（manifest 从此生成）
├── package.json               # React 19 + WXT + Tailwind v4 + shadcn/ui
├── tsconfig.json
├── components.json            # shadcn/ui 配置 (new-york style)
├── public/
│   └── assets/                # 图标、Logo 等静态资源
├── src/
│   ├── entrypoints/
│   │   ├── background.ts      # Service Worker，TypeScript 重写，保留 WS 通信逻辑
│   │   └── sidepanel/
│   │       ├── index.html     # WXT 自动处理
│   │       ├── main.tsx       # React 挂载点
│   │       └── App.tsx        # 主应用（视图路由 + 布局）
│   ├── components/
│   │   ├── ui/                # shadcn/ui 原语（button, card, input, textarea 等）
│   │   ├── ChatView.tsx       # 聊天视图
│   │   ├── EventCards.tsx     # 事件卡片系统
│   │   ├── HistoryList.tsx    # 历史会话列表
│   │   ├── HistoryDetail.tsx  # 会话详情
│   │   ├── ConfigPanel.tsx    # 配置面板
│   │   └── misc.tsx           # StatusDot, Logo, EmptyState 等
│   ├── hooks/
│   │   ├── useWebSocket.ts    # 封装 WS 通信为 React hook
│   │   └── useConfig.ts       # 配置持久化 hook
│   ├── lib/
│   │   ├── ws-client.ts       # 从现有 ws-client.js 迁移（加类型）
│   │   ├── idb.ts             # IndexedDB 会话持久化
│   │   └── utils.ts           # cn() 等工具函数
│   ├── assets/
│   │   └── index.css          # Tailwind 入口 + oklch CSS 变量主题
│   └── types/
│       └── index.ts           # 消息类型、事件类型等 TypeScript 定义
├── content/
│   └── content.js             # 保持原生 JS 不动，通过 WXT unlisted 加载
└── test/
    └── ...                    # 现有测试迁移
```

### 构建配置

- **WXT 0.20+** + Vite，`wxt.config.ts` 中声明 manifest 权限（sidePanel, scripting, tabs, debugger, alarms, activeTab, host_permissions: `<all_urls>`）
- **content.js**：通过 `chrome.scripting.executeScript` 动态注入，不声明为 WXT content script entrypoint
- **Tailwind v4**：`@tailwindcss/vite` 插件
- **shadcn/ui**：new-york 风格，按需引入组件

## 3. 通信架构

### 整体架构（保持不变）

```
[Python agent-core] ←WebSocket→ [background.ts] ←chrome.runtime→ [sidepanel React UI]
                                       ↓ chrome.tabs.sendMessage
                                  [content.js (原生 JS)]
```

### 消息类型

```typescript
// types/index.ts

/** 侧边面板 ↔ 后台的消息 */
interface SidepanelMessage {
  type: 'user_message' | 'mode_change' | 'get_status' | 'get_events'
  content?: string
  mode?: 'ai' | 'manual'
}

/** 后台 → 侧边面板的消息 */
interface BackgroundMessage {
  type: 'stream' | 'error' | 'status_update' | 'event'
  content?: string
  status?: 'connected' | 'disconnected'
  event?: AgentEvent
  error?: string
}

/** 后台 ↔ 内容脚本的消息（保持现有格式不变） */
interface ContentMessage {
  action: 'parse_dom' | 'get_element_info' | 'click' | 'input_text' |
          'scroll' | 'enable_overlay' | 'disable_overlay'
  // ... 其余字段保持现有 content.js 的格式
}

/** UI 层消息 */
interface Message {
  id: string
  role: 'user' | 'agent' | 'system'
  content: string
  timestamp: number
  status?: 'streaming' | 'done' | 'error'
  events?: AgentEvent[]
}

/** Agent 事件（用于事件卡片） */
interface AgentEvent {
  type: 'step' | 'observation' | 'error' | 'result' | 'retry' | 'activity'
  data: Record<string, unknown>
  timestamp: number
}
```

### useWebSocket Hook

核心 React hook，封装所有 sidepanel ↔ background 通信：

```typescript
interface UseWebSocketReturn {
  status: 'connected' | 'disconnected'
  sendTask: (content: string) => void
  messages: Message[]
  isStreaming: boolean
  stopStream: () => void
  error: string | null
  mode: 'ai' | 'manual'
  setMode: (mode: 'ai' | 'manual') => void
}
```

**流式消息处理**：
- background 转发 `{ type: 'stream', content }` 消息
- hook 内部维护当前 agent 消息，收到新 chunk 时追加文本
- `[DONE]` 标记流结束，消息归档到 `messages` 数组
- `[BUSY]` 显示系统提示

### useConfig Hook

```typescript
interface AppConfig {
  wsUrl: string
  model: string
  token: string
}

// chrome.storage.local 持久化，页面加载时读取，保存时写入
```

### background.ts

从现有 `background.js` TypeScript 重写，改动最小化：
- WS 客户端逻辑不变，加类型注解
- 消息路由不变（上行 user_message → WS，下行 stream → sidepanel，action → content）
- 保留 `chrome.alarms` keep-alive 机制
- 保留 `chrome.scripting.executeScript` 动态注入 content.js 的逻辑

## 4. UI 组件与视图

### App.tsx 视图路由

联合类型路由，无路由库：

```typescript
type View =
  | { name: 'chat' }
  | { name: 'config' }
  | { name: 'history' }
  | { name: 'history-detail'; sessionId: string }
```

布局：
```
┌─────────────────────────────┐
│ Header (Logo + 标题)         │
├─────────────────────────────┤
│ StatusBar (状态点 + 连接文字  │
│   + 模式指示 + 设置/历史按钮) │
├─────────────────────────────┤
│ ViewContainer                │
│ (根据 view state 切换)       │
├─────────────────────────────┤
│ Footer (版本号)              │
└─────────────────────────────┘
```

### ChatView

- 未聊天时显示 EmptyState（呼吸渐变 + 打字机欢迎语）
- 消息列表：用户气泡（靠右）、agent 事件卡片（靠左）、系统消息（居中）
- 底部 InputGroup：Textarea + 发送/停止按钮
- Enter 发送，Shift+Enter 换行，IME 期间禁用 Enter
- 首次发送自动切换空状态到聊天
- 流式接收时自动滚动到底部

### EventCards（事件卡片系统）

| 卡片 | 左边框色 | 用途 |
|------|---------|------|
| StepCard | 蓝色 | agent 推理步骤（思考 + 操作 + 结果） |
| ObservationCard | 绿色 | 页面状态观察 |
| ErrorCard | 红色 | 错误信息 |
| RetryCard | 琥珀色 | 重试提示 |
| ResultCard | — | 任务最终结果 |
| ActivityCard | 脉冲动画 | 当前活动指示 |

每张卡片支持可展开的 RawSection（调试用原始数据）。

### HistoryList

- 从 IndexedDB 加载会话列表
- 每项：状态图标、任务文本、时间戳、步骤数
- 悬停操作：重新运行、导出 JSON、删除
- 支持清空全部

### HistoryDetail

- 复用 EventCards 组件（只读模式）
- 顶部：任务文本 + 重新运行/删除按钮

### ConfigPanel

参考项目的 Field 组件族：
- WebSocket URL（文本输入 + 复制按钮）
- 模型选择（下拉框）
- 认证令牌（密码输入 + 显示/隐藏）
- 保存/取消按钮

### UI 原语（从参考项目移植）

从 `components/ui/` 按需引入：button, card, input, textarea, input-group, separator, label, field, spinner, typing-animation, item

### 动画与视觉效果

- **EmptyState**：呼吸径向渐变（oklch）+ TypingAnimation 循环欢迎语
- **StatusDot**：彩色圆点 + 脉动动画（连接绿/断开红/运行中蓝）
- **MotionOverlay**：agent 运行时全屏发光边框（适配 WS 模式）

## 5. 主题系统

### CSS 变量（oklch 色彩空间）

```css
:root {
  --background: oklch(1 0 0);
  --foreground: oklch(0.145 0 0);
  --primary: oklch(0.205 0.08 265);
  --muted: oklch(0.97 0 0);
  --destructive: oklch(0.577 0.245 27.33);
  --border: oklch(0.922 0 0);
  --ring: oklch(0.708 0.165 254.62);
  /* 完整 shadcn/ui token */
}

.dark { /* 暗色覆盖 */ }
```

- 暗色模式：`matchMedia('(prefers-color-scheme: dark)')` 检测
- Tailwind v4 `@theme inline` 映射变量到工具类
- 工具函数：`cn()` = `clsx` + `tailwind-merge`

## 6. 状态管理

纯 React hooks，无外部状态库：

| 层级 | Hook | 状态 |
|------|------|------|
| App | `useState<View>` | 视图路由 |
| ChatView | `useWebSocket()` | 消息、流式状态、发送/停止 |
| ConfigPanel | `useConfig()` | 配置读写 + chrome.storage.local |
| HistoryList/Detail | `useIdb()` | IndexedDB 会话持久化 |

### 数据流

```
用户输入 → sendTask() → chrome.runtime.sendMessage → background.ts → WS → agent-core
                                                                               ↓
UI 更新  ← useWebSocket 状态 ← chrome.runtime.onMessage ← background.ts ← WS stream
```

## 7. 会话持久化（IndexedDB）

```typescript
interface Session {
  id: string
  task: string
  messages: Message[]
  events: AgentEvent[]
  status: 'running' | 'completed' | 'error'
  createdAt: number
}
```

- 聊天完成/出错时自动保存
- 历史列表按 `createdAt` 降序
- 导出为 JSON（任务名 + 时间戳命名）

## 8. content.js 兼容

- 保持 IIFE 格式，通过 WXT unlisted content script 方式加载（`defineContentScript({ matches: [], main() })` + `chrome.scripting.executeScript` 动态注入）
- background.ts 保留 `chrome.scripting.executeScript` 动态注入逻辑
- 所有 content ↔ background 消息格式保持不变
- 现有 content.js 测试保持有效

## 9. 不做的事

- 不引入内嵌 agent（保持 WS 架构）
- 不重构 content.js（保持原生 JS）
- 不引入外部状态管理库（Redux/Zustand 等）
- 不实现 Hub 模式（参考项目有，当前项目不需要）
- 不实现参考项目的多标签页管理（TabsController）— 当前项目通过后端 agent 控制
