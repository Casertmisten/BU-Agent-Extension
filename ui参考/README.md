# Page Agent Extension（UI 参考）

> 本目录是 [alibaba/page-agent](https://github.com/alibaba/page-agent) Chrome 扩展的 UI 参考副本，用于为新项目提供 UI 样式和交互逻辑的参考。

## 项目简介

Page Agent 是一个 AI 驱动的浏览器自动化 Chrome 扩展。用户通过自然语言描述任务，LLM Agent 自主操作浏览器标签页完成任务——点击、填写表单、翻页、滚动、提取数据等。支持多标签页工作流，可通过侧边栏、WebSocket Hub 或网页注入 API 三种方式驱动。

---

## 目录结构

```
ui参考/
├── components/              # shadcn 风格的通用 UI 基础组件（Radix + Tailwind）
│   ├── ui/                  # 原子组件：button, card, input, textarea, switch, spinner 等
│   ├── cards.tsx             # 事件卡片：StepCard、EventCard、ActivityCard
│   ├── HistoryList.tsx       # 历史会话列表（IndexedDB 存储）
│   ├── HistoryDetail.tsx     # 历史会话详情回放
│   ├── ConfigPanel.tsx       # 配置面板（LLM 端点、API Key、语言等）
│   ├── ErrorBoundary.tsx     # React 错误边界
│   └── misc.tsx              # 杂项：StatusDot、Logo、MotionOverlay、EmptyState
│
├── extension/               # Chrome 扩展主体（WXT 框架）
│   ├── src/
│   │   ├── entrypoints/     # 5 个入口点
│   │   │   ├── sidepanel/   # 侧边栏 React 应用（主要 UI）
│   │   │   ├── hub/         # WebSocket Hub 应用（外部程序控制）
│   │   │   ├── background.ts     # Service Worker，消息路由
│   │   │   ├── content.ts        # 内容脚本，DOM 操作代理
│   │   │   └── main-world.ts     # 主世界注入，暴露 window.PAGE_AGENT_EXT API
│   │   ├── agent/           # Agent 核心逻辑
│   │   │   ├── MultiPageAgent.ts           # 多标签页 Agent 主类
│   │   │   ├── useAgent.ts                 # React Hook 封装 Agent
│   │   │   ├── TabsController.ts           # 标签页生命周期管理
│   │   │   ├── RemotePageController.ts     # DOM 操作远程代理
│   │   │   ├── tabTools.ts                 # 自定义工具（开/关/切换标签页）
│   │   │   ├── system_prompt.md            # Agent 系统提示词
│   │   │   └── constants.ts                # 默认配置
│   │   └── components/      # 与顶层 components/ 内容相同（扩展内副本）
│   └── wxt.config.js        # WXT 构建配置
│
└── ui/                      # @page-agent/ui 包（框架无关的纯 JS UI 库）
    └── src/
        ├── panel/           # Panel 类：纯 DOM 的 Agent 控制面板（无 React）
        │   ├── Panel.ts         # 面板主逻辑：渲染、事件、展开/折叠
        │   ├── Panel.module.css # 面板样式
        │   ├── cards.ts         # 事件卡片渲染逻辑
        │   └── types.ts         # PanelAgentAdapter 接口定义
        ├── motion-css/      # CSS 动画效果（运行时的渐变发光边框）
        └── i18n/            # 国际化（中英文）
```

---

## 技术栈

| 类别 | 技术 |
|------|------|
| 扩展框架 | **WXT** (Web Extension Tools) |
| UI 框架 | **React 19** + **Tailwind CSS v4** |
| 组件库 | **Radix UI** primitives（shadcn 风格封装） |
| 动画 | **motion** (Framer Motion)、**ai-motion**（发光边框）、自定义 CSS 动画 |
| 数据持久化 | **IndexedDB**（via `idb`）、`chrome.storage.local` |
| Schema 验证 | **Zod v4** |
| 图标 | **lucide-react**、**simple-icons** |
| 构建 | **Vite**（通过 WXT） |
| 国际化 | 自实现 i18n（Mustache 模板插值） |

---

## 核心架构

### 入口点

| 入口 | 文件 | 作用 |
|------|------|------|
| **Background** | `background.ts` | Service Worker，路由消息（TAB_CONTROL / PAGE_CONTROL），管理标签页事件广播，生成认证 token |
| **Sidepanel** | `sidepanel/App.tsx` | 侧边栏 React 应用，主交互界面：任务输入、事件流展示、历史浏览、配置 |
| **Hub** | `hub/App.tsx` | WebSocket 客户端，允许外部程序通过 WS 协议发送任务，双栏布局（协议文档 + 实时会话） |
| **Content Script** | `content.ts` | 注入所有页面，初始化 `PageController` 处理 DOM 操作 |
| **Main World** | `main-world.ts` | 注入页面主世界，暴露 `window.PAGE_AGENT_EXT.execute(task, config)` API |

### 消息流

```
Sidepanel / Hub（React 应用）
    │
    ▼
useAgent() Hook ──► MultiPageAgent
    │                    │
    │                    ├─► TabsController ──► Background ──► Chrome Tabs API
    │                    │
    │                    └─► RemotePageController ──► Background ──► Content Script ──► DOM
    │
    ▼
Content Script ◄──► Main World（window.PAGE_AGENT_EXT）
```

### Agent 系统

- **MultiPageAgent**：继承自 `@page-agent/core` 的 `PageAgentCore`，组合 `TabsController` 和 `RemotePageController`，支持多标签页自动化
- **useAgent()**：React Hook，封装 Agent 为响应式状态（status / history / activity / currentTask / config）
- **System Prompt**：定义 Agent 为浏览器自动化 Agent，包含浏览器操作规则、输出格式（JSON：evaluation / memory / next_goal / action）

---

## UI 组件层次

### 侧边栏应用（Sidepanel）

```
App
 ├─ 视图路由（chat | config | history | history-detail）
 │
 ├─ Chat 视图：
 │    ├─ <header> — Logo、状态指示灯、历史按钮、设置按钮
 │    ├─ <main>
 │    │    ├─ 任务横幅（currentTask）
 │    │    ├─ 事件流列表
 │    │    │    ├─ EventCard[] — 每个 Agent 步骤的卡片
 │    │    │    └─ ActivityCard — 运行中状态的动态指示器
 │    │    └─ <footer> — 输入框 + 发送/停止按钮
 │    └─ MotionOverlay — 运行时的发光边框动画
 │
 ├─ Config 视图：<ConfigPanel> 设置表单
 ├─ History 视图：<HistoryList> 会话列表
 └─ History Detail 视图：<HistoryDetail> 会话回放
```

### Hub 应用

```
App
 ├─ <aside> — 左栏：文档、配置、协议说明
 └─ <main> — 右栏：
      ├─ WS 连接状态
      ├─ 任务横幅
      └─ 事件流（EventCard[]、ActivityCard）
```

### 关键 UI 组件说明

| 组件 | 交互逻辑 |
|------|----------|
| **EventCard** | 展示 Agent 单步执行事件（反思 + 动作），支持折叠/展开 |
| **ActivityCard** | Agent 运行中的过渡态指示器，显示当前活动描述 |
| **HistoryList** | 从 IndexedDB 加载历史会话，支持删除、重跑、导出 |
| **HistoryDetail** | 只读回放某个历史会话的全部事件 |
| **ConfigPanel** | 配置表单：Base URL、模型名、API Key、语言、最大步数、系统指令等 |
| **InputGroup** | 输入区域，包含自适应高度的 textarea 和发送/停止按钮 |
| **MotionOverlay** | Agent 运行时的 CSS 渐变发光边框动画效果 |
| **StatusDot** | 运行状态圆点指示灯（绿色运行/灰色空闲） |

---

## 交互逻辑要点

1. **任务执行流程**：用户输入任务 → `useAgent().execute(task)` → Agent 循环执行步骤 → 每步生成事件卡片 → 完成时保存会话到 IndexedDB
2. **事件卡片**：每个 Agent 步骤渲染为 `StepCard`，包含 evaluation（上步评估）+ action（本步动作），可折叠查看详情
3. **运行状态反馈**：运行时显示 `StatusDot`（绿色）、`ActivityCard`（当前活动）、`MotionOverlay`（边框发光）
4. **历史管理**：任务完成后自动持久化，支持在历史列表中浏览、删除、重跑、导出 JSON
5. **配置持久化**：设置保存到 `chrome.storage.local`，重启扩展后自动恢复
6. **WebSocket Hub**：外部程序连接后可发送 `{ type: "execute", task: "..." }` 驱动 Agent，结果通过 `{ type: "result" }` 返回

---

## 参考 value

本项目对新项目的参考价值：

| 参考点 | 说明 |
|--------|------|
| 事件卡片 UI | `cards.tsx` — Agent 步骤的卡片渲染方式（折叠/展开、类型区分） |
| 聊天交互 | `sidepanel/App.tsx` — 输入框 + 事件流 + 状态指示的整体布局 |
| Agent Hook | `useAgent.ts` — 将 Agent 封装为 React 响应式状态的范式 |
| 配置面板 | `ConfigPanel.tsx` — LLM 配置表单的 UI 结构 |
| 动画效果 | `motion-css/` — 纯 CSS 的运行状态发光边框动画 |
| 历史记录 | `HistoryList.tsx` / `HistoryDetail.tsx` — 会话持久化和回放的交互 |
| 纯 DOM Panel | `ui/src/panel/Panel.ts` — 不依赖 React 的嵌入式面板实现 |
| 国际化 | `ui/src/i18n/` — 轻量 i18n 方案（Mustache 模板 + TypeScript 类型推导） |
