# Browser Use Agent

基于 Chrome 扩展 + Python 后端的 AI 浏览器自动化工具。用户在 SidePanel 中输入自然语言指令，Agent 自动操控浏览器完成任务。

## 架构

```
┌──────────────────┐     WebSocket     ┌──────────────────┐
│  Chrome 扩展      │ ◄──────────────► │  agent-core      │
│  (SidePanel UI)   │   ws://8765      │  (Python 服务端)  │
│  Background       │                  │  agentscope v2   │
│  Content Script   │                  │  LLM + VLM       │
└──────────────────┘                  └──────────────────┘
```

- **chrome-extension**：基于 WXT + React + Tailwind 构建的 Chrome 扩展，提供 SidePanel 聊天界面，通过 WebSocket 与后端通信，执行 DOM 解析、点击、输入、截图、导航等浏览器操作。
- **agent-core**：基于 agentscope v2 的 Python WebSocket 服务端，接收用户指令后调用 LLM/VLM 进行推理，将操作指令下发到 Chrome 扩展执行。

## 快速开始

### 前置要求

- Python >= 3.11
- Node.js >= 18
- uv（Python 包管理器）
- Chrome 浏览器

### 1. 启动后端

```bash
cd agent-core

# 复制环境变量文件，填入你的 API Key
cp .env.example .env

# 安装依赖
uv sync

# 启动服务
uv run python server.py
```

### 2. 构建扩展

```bash
cd chrome-extension

# 安装依赖
npm install

# 构建
npm run build
```

构建产物在 `chrome-extension/.output/chrome-mv3/`。

### 3. 加载扩展

1. 打开 Chrome，访问 `chrome://extensions/`
2. 开启「开发者模式」
3. 点击「加载已解压的扩展程序」
4. 选择 `chrome-extension/.output/chrome-mv3/` 目录

### 4. 使用

点击扩展图标打开 SidePanel，输入任务描述即可。例如：

> 帮我打开百度搜索"天气预报"

Agent 会自动解析页面 DOM、定位元素、执行点击和输入操作。DOM 操作失败时会降级到截图分析 + 坐标点击。

**新建会话**：SidePanel 顶部的「+」按钮用于新建会话。点击后后端会重建对话上下文（清空历史、换新会话 ID），开始一段全新对话；若此时 Agent 正在执行任务，会先停止当前任务再重置。历史会话仍保留在前端历史记录中，可随时回看。

**技能（Skill）**：SidePanel 输入框下方有一个「✦ 技能」按钮。点击会弹出当前可用技能列表（名称 + 描述），选中某项后会在输入框填入 `/skill <技能名> `（光标停在末尾），你可以补充具体任务再发送。Agent 会自动读取该技能的完整指令并按其执行。

技能是一份 `SKILL.md` 指令文档（带 YAML frontmatter 的 `name`/`description` + markdown 正文）。后端默认从 `agent-core/skills/` 目录加载（递归扫描子目录），可在 `agent-core/config.yaml` 的 `skills.dirs` 追加更多目录：

```yaml
skills:
  dirs:
    - "./skills"
    - "/path/to/your/skills"   # 自定义目录
```

新增技能：在已配置的目录下创建 `<技能名>/SKILL.md`，重启后端即可。示例见 `agent-core/skills/example/SKILL.md`。

**录制操作沉淀为技能**：SidePanel 输入框旁的「● 录制」按钮可把你的浏览器操作直接沉淀为技能。点击开始录制 → 在页面上正常操作 → 点击停止 → 确认保存后，后端会自动把这段操作轨迹交给 LLM 蒸馏成 `SKILL.md` 并安装到技能目录，无需手写。

完整流程：

1. 点击「● 录制」开始，扩展 content script 会捕获你的点击、输入、页面跳转等操作（事件自动脱敏，过滤密码等敏感字段）。
2. 操作完成后点击「■ 停止」，此时仅结束采集、不立即蒸馏，可在确认面板选择「保存」或「丢弃」。
3. 选择「保存」即触发蒸馏：后端将轨迹切片（atomize）→ LLM 归纳为结构化指令（distill）→ 写入 `SKILL.md` + frontmatter（install），同名技能下次启动即可用。

蒸馏默认复用 `llm` 段模型，可在 `agent-core/config.yaml` 的 `recorder` 段单独配置：

```yaml
recorder:
  distill_model: null           # null 表示复用 llm.model
  batch_size: 500               # 单批上传事件数上限
  buffer_flush_threshold: 5000  # 内存缓冲落盘阈值
```

## 配置

### 后端配置（agent-core）

通过 `.env` 文件或环境变量配置：

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `LLM_PROVIDER` | LLM 提供商（dashscope / openai） | `dashscope` |
| `LLM_MODEL` | LLM 模型名称 | `glm-5.1` |
| `LLM_API_KEY` | LLM API Key | - |
| `VLM_PROVIDER` | VLM 提供商 | `dashscope` |
| `VLM_MODEL` | VLM 模型名称 | `qwen3.6-35b-a3b` |
| `VLM_API_KEY` | VLM API Key | - |
| `SERVER_HOST` | WebSocket 监听地址 | `localhost` |
| `SERVER_PORT` | WebSocket 端口 | `8765` |
| `DOM_STRATEGY` | DOM 解析策略（ax / flat / tree） | `ax` |

### 扩展权限

扩展需要以下 Chrome 权限：`sidePanel`、`scripting`、`tabs`、`debugger`、`activeTab`、`storage`、`alarms`，以及 `<all_urls>` 的主机权限。

## 项目结构

```
BU-Agent-Extension/
├── chrome-extension/          # Chrome 扩展
│   ├── src/
│   │   ├── entrypoints/       # WXT 入口（background, sidepanel）
│   │   ├── components/        # React 组件（ChatView, ConfigPanel, HistoryList 等）
│   │   ├── hooks/             # 自定义 Hooks（useWebSocket, useConfig, useRecorder）
│   │   ├── capture/           # 录制捕获（action/mutation recorder + 脱敏 redactor）
│   │   ├── lib/               # 工具库（ws-client, idb, utils）
│   │   └── types/             # TypeScript 类型定义
│   ├── public/content/        # Content Script（含录制入口 recorder.content）
│   └── wxt.config.ts          # WXT 构建配置
├── agent-core/                # Python 后端
│   ├── agent/                 # Agent 核心（BrowserAgent、模型工厂、提示词）
│   │   ├── agent.py           # BrowserAgent 类：模型+工具+状态组合
│   │   ├── model.py           # 模型工厂（openai/dashscope）
│   │   └── prompts.py         # 系统提示词
│   ├── recorder/              # 录制蒸馏管线（轨迹→技能）
│   │   ├── pipeline.py        # 编排：atomize → distill → install
│   │   ├── atomizer.py        # 轨迹切片
│   │   ├── distiller.py       # LLM 蒸馏 + JSON 容错解析
│   │   ├── installer.py       # 写入 SKILL.md + frontmatter
│   │   └── event_utils.py     # 事件归一化与文本摘要
│   ├── server.py              # WebSocket 服务器入口
│   ├── browser/               # 浏览器连接与工具（DOM 操作、截图等）
│   ├── config_loader.py       # 配置加载
│   ├── logger.py              # 日志模块
│   └── config.yaml            # 默认配置模板
└── docs/                      # 文档
```

## 开发

```bash
# 后端开发（热重载需手动重启）
cd agent-core && uv run python server.py

# 扩展开发（WXT 热重载）
cd chrome-extension && npm run dev
```

## 许可

私有项目，未公开许可。
