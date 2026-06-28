# 录制用户操作沉淀为技能（Recording → Skill）设计

> 日期：2026-06-28
> 参考项目：`/Users/heren/code/Browser-BC`
> 状态：已确认，待编写实现计划

## 1. 目标与范围

### 1.1 目标

用户在浏览器中操作一次，扩展捕获完整操作步骤，经 LLM 蒸馏为一份 **`SKILL.md`（自然语言操作手册）**，落入现有技能目录，**立即**可在 Agent 对话中触发使用。

### 1.2 核心决策（来自 brainstorming）

| 维度 | 决策 |
|---|---|
| 技能形态 | **自然语言手册**（SKILL.md），与现有技能系统 100% 兼容，不提供确定性回放 |
| 蒸馏复杂度 | **中度**：录制捕获层全量照搬 Browser-BC；蒸馏保留 atomize + distill 两阶段；classify/bucket/合并留扩展接口不实现 |
| 录制入口 | **SidePanel 按钮**，与现有「✦ 技能」按钮并列 |
| 蒸馏位置 | **agent-core 后端**，复用现有 WebSocket 服务，不新增服务 |
| 传输通道 | **复用现有 WS**（`ws://localhost:8765`），新增 3 条 `record_*` 消息类型 |

### 1.3 非目标（YAGNI）

- ❌ 确定性回放（点击序列重放）
- ❌ classify / bucket / 能力桶归并与增量合并（留接口，未来实现）
- ❌ 语义检索 registry（`query_top_k`）
- ❌ TRACE_GUIDE.md / evidence.jsonl 副产物
- ❌ 蒸馏结果的结构化字段（preconditions/milestones/red_lines 等），全部融入 skill_md 正文
- ❌ 控制面板（app/dist）
- ❌ Tauri 桌面壳、PyInstaller 打包

## 2. 整体架构与数据流

```
┌─ chrome-extension（前端）──────────────────────────────┐
│ SidePanel [● 录制] 按钮（与"✦ 技能"并列）              │
│     │ click start                                      │
│     ▼                                                   │
│ background.ts                                          │
│   ├─ 向目标 tab 动态注入 content recorder（仅录制时）   │
│   ├─ 维护唯一 activeRecordSession（崩溃可恢复）         │
│   └─ 接收 content 的 {type:'record_event'} 消息 → 聚合  │
│     │                                                   │
│ Content Script（照搬 Browser-BC 的 capture/）          │
│   ├─ action-recorder  DOM 事件捕获 + 去重节流          │
│   ├─ selector          稳定选择器/xpath 生成           │
│   ├─ mutation-summary  DOM 变更批量摘要                │
│   └─ redactor          密码/邮箱/支付脱敏              │
│     │ chrome.runtime.sendMessage                       │
│     ▼                                                   │
│ background.ts 聚合到内存（超量落盘 IndexedDB）          │
│     │ stop → 分批 ≤500 事件/批                          │
│     ▼                                                   │
│   现有 WS ws://localhost:8765                           │
│   新增消息：record_start / record_event / record_stop  │
└─────────────┬──────────────────────────────────────────┘
              ▼
┌─ agent-core（后端，复用现有 WS 服务）──────────────────┐
│ server.py 新增 record_* 处理                            │
│   ├─ 组装 TraceEnvelope（schema_version/trace_id/...）  │
│   ├─ atomizer   切片（域名切换/闲置>15s/submit 后导航） │
│   ├─ distiller  复用 agentscope model → SKILL.md       │
│   └─ installer  写入 agent-core/skills/<name>/SKILL.md │
│     │                                                   │
│     ▼                                                   │
│ LocalSkillLoader 实时扫描 → 技能立即生效（无需重启）    │
└─────────────────────────────────────────────────────────┘
```

**核心设计原则：**
- **录制层**：照搬 Browser-BC 的 `capture/` 全套（去重节流是录制的灵魂，不能简化）
- **传输层**：复用现有 WS，新增 3 个消息类型，零新服务
- **蒸馏层**：中度——保留 atomize + distill，classify/bucket 留接口不实现
- **产物层**：直接落入现有 `agent-core/skills/`，与现有技能系统 100% 兼容

## 3. 录制捕获层

完全照搬 Browser-BC 的 `capture/` 模块，适配到 BU-Agent 的 content script 动态注入机制。

### 3.1 监听的事件（捕获阶段，`capture:true, passive:true`）

| 类别 | 事件 | 处理 |
|---|---|---|
| 鼠标 | click, dblclick, dragstart→drag, drop, contextmenu | 记录 target ElementRef + coords |
| 输入 | input, change, submit, file input→`file_select` | value 经 redactor 脱敏 |
| 键盘 | keydown | **只录快捷键**（Ctrl/Meta/Alt 或 Enter/Esc/Tab/Backspace/Delete），过滤普通字符 |
| 滚动 | scroll | **250ms 节流**，区分 window/元素，各自去重 |
| 焦点 | focus, blur | 记录目标元素 |
| 标记 | copy/cut（不存内容）, paste, compositionstart/end | 只存 key 标记 |
| 选区 | selectionchange | 只存 length |

### 3.2 去重/降噪（录制的灵魂，不可简化）

1. **滚动节流**：`SCROLL_THROTTLE_MS = 250`，window 用变量，元素用 `WeakMap<EventTarget, number>`
2. **键盘过滤**：`isShortcut()` 过滤掉普通字符输入
3. **DOM 变更摘要**：`MutationObserver` + debounce(500ms) / minFlush(2s)，只存统计数 + signals + selectors + 文本采样，**不存全量变更日志**
4. **DOM 快照去重**：按 hash 去重，只在关键 action 后补快照

### 3.3 ElementRef（元素定位，distill 的关键）

优先级：`id` → 稳定属性（data-testid/data-test/data-cy/aria-label/name/title）→ `role` → 带 nth-of-type 的层级路径 → 回退 xpath。每次都用 `querySelectorAll` 验证唯一性。

### 3.4 隐私脱敏（redactor）

密码/邮箱/支付/OTP/token 用 `RedactedValue` 包装，默认不存原始内容，只存 `raw_removed` + 类型标记。

### 3.5 文件归属（照搬 Browser-BC）

| 新文件（BU-Agent 内） | 照搬自 Browser-BC |
|---|---|
| `chrome-extension/src/capture/types.ts` | `shared/types.ts`（12 种事件 + ElementRef + envelope） |
| `chrome-extension/src/capture/action-recorder.ts` | `capture/action-recorder.ts` |
| `chrome-extension/src/capture/selector.ts` | `capture/selector.ts` |
| `chrome-extension/src/capture/mutation-summary-recorder.ts` | `capture/mutation-summary-recorder.ts` |
| `chrome-extension/src/capture/redactor.ts` | `redaction/redactor.ts` |
| `chrome-extension/src/capture/recorder.ts` | `recording/recorder.ts`（start/stop/appendEvent） |

### 3.6 注入方式的关键适配

BU-Agent 现有的 `content.js` 是**静态放在 `public/content/`、通过 manifest 静态注册**的。录制捕获是 TypeScript 模块化代码，需要决定怎么进入页面。

**适配方案**：录制捕获代码**走 WXT 的 content script 编译管线**，编译成独立 chunk，在 `background.ts` 收到 `record_start` 后用 `chrome.scripting.executeScript` **动态注入**到目标 tab（而非 manifest 静态注册）。停止录制时清理 listener。这样：
- 非录制态零开销（不注入、不监听）
- 与现有静态 `content.js` 共存不冲突（两者职责正交：一个执行 Agent 指令，一个录制用户操作）
- 复用 WXT 的 TS 编译能力

## 4. 传输层（WS 消息协议）

在现有 `ws://localhost:8765` 上新增 3 条消息类型，前后端协议对齐。复用 `background.ts` 现有路由，不新增服务。

### 4.1 前端 → 后端（`SidepanelMessage` 扩展）

```typescript
// chrome-extension/src/types/index.ts 新增
| { type: 'record_start'; tab_id: number; label?: string }
| { type: 'record_event'; trace_id: string; events: TraceEvent[]; seq: number }  // 批量
| { type: 'record_stop'; trace_id: string; label?: string }
| { type: 'record_redistill'; trace_id: string }   // 蒸馏失败后重试
```

- **`record_event` 批量发送**：`background.ts` 在录制期间聚合 content 发来的单条事件到内存缓冲，**满 500 条或收到 `record_stop` 时整批发送**，带 `seq` 递增序号便于后端去重/排序
- `trace_id` 由 `background.ts` 在 `record_start` 时生成（UUID），贯穿整条录制链路

### 4.2 后端 → 前端（`BackgroundMessage` 扩展）

```typescript
| { type: 'record_started'; trace_id: string }
| { type: 'record_progress'; received_events: number; seq: number }
| { type: 'record_distilling'; trace_id: string }       // 进入蒸馏阶段
| { type: 'record_distill_progress'; stage: 'atomize'|'distill'|'install'; message: string }
| { type: 'record_done'; trace_id: string; skill_name: string; skill_path: string }
| { type: 'record_error'; trace_id: string; stage: string; message: string }
```

- 蒸馏过程会调 LLM（耗时数秒到数十秒），用 `record_distill_progress` 给前端实时反馈
- `record_done` 带回 `skill_name`，前端提示「技能 `xxx` 已生成，立即可用」

### 4.3 后端处理流程（`agent-core/server.py` 新增）

```
record_start  → 创建录制会话上下文（trace_id → 事件列表缓冲）
record_event  → 校验 trace_id，追加事件（按 seq 去重）
record_stop   → 组装 TraceEnvelope → 触发蒸馏 task
                 ├─ atomize：切片
                 ├─ distill ：agentscope model 调用 → SKILL.md
                 └─ install ：写入 agent-core/skills/<name>/SKILL.md
                    → 推 skills_list（刷新前端技能列表）
                    → 推 record_done
```

### 4.4 关键约束

- **单用户本地单连接**：WS 无并发竞争，`record_*` 与 `user_message` 通过 `asyncio.create_task` 隔离，蒸馏不阻塞对话
- **消息大小**：单批 ≤500 事件，本地连接无硬上限，但避免巨型 JSON
- **错误隔离**：蒸馏失败经 `record_error` 回传，不影响 WS 主连接和 Agent 对话
- **边界**：`record_*` 消息**不进入** `BrowserAgent.run()` 流程，不走 `BrowserConnection.send_action()` 往返，完全独立的处理分支

## 5. 蒸馏层

中度方案：保留 **atomize（切片）+ distill（蒸馏）**两阶段，classify/bucket 留扩展接口不实现。完全复用 agentscope 的 model 工厂调用 LLM。

### 5.1 阶段 1：Atomize（切片）

照搬 Browser-BC 的 `harness/atomizer.py`，把长轨迹切成语义段，降低单次 LLM context 压力。

**切分边界规则**（任一命中即切片）：
- 域名切换
- 闲置 > 15 秒（相邻事件 timestamp 差）
- 同域路径前缀（深度 2）变化
- submit 后发生导航

**噪音过滤**：
- Stripe / reCAPTCHA 等 iframe 内的事件
- 孤立的修饰键（Shift/Ctrl 单独按下）
- 2 秒内同一元素的重复点击（保留首末）

**段归域**：每段按段内主导域名归域，作为后续 skill 命名的依据。

> **扩展接口预留**：`atomizer` 输出的 `Segment[]` 结构里保留 `bucket_id`、`capability` 字段（初版置空），未来 classify/bucket 阶段可直接填充。

### 5.2 阶段 2：Distill（蒸馏）

参考 Browser-BC 的 `distiller.py`，但**简化为单段或合并多段一次性蒸馏**，不做增量合并。

**输入**：`Segment[]`（每段含事件序列 + 主导域名 + 段摘要）
**输出**：一份 `SKILL.md` + 元信息

**LLM Prompt 结构**（要求模型输出 JSON）：

```
system: 你是浏览器操作技能蒸馏专家。将用户录制的事件序列提炼为
        AI Agent 可执行的自然语言操作手册。

user:   ## 录制信息
        域名：{domain}  标签：{label}  事件数：{n}

        ## 事件序列（已脱敏）
        {events_summary}   # 经 event_utils.summarize_events 转成的文本

        ## 任务
        输出 JSON：
        {
          "skill_name": "kebab-case",
          "description": "一句话描述技能用途（≤80字，用于 Agent 触发匹配）",
          "skill_md": "完整 markdown 正文（不含 frontmatter）"
        }

        skill_md 要求：
        - 聚焦「做什么」而非「点哪里」，不要写死选择器
        - 用"点击登录按钮""输入用户名"这样的自然语言
        - 覆盖前置条件、关键步骤、终止条件
```

**关键简化**（相对 Browser-BC）：
- ❌ 去掉 `preconditions/milestones/terminal_conditions/false_terminal_states/recovery_policies/anti_drift_boundaries/red_lines` 等结构化字段 → 让模型自由组织进 `skill_md` 正文
- ❌ 去掉 `TRACE_GUIDE.md`、`evidence.jsonl` 副产物
- ❌ 去掉增量蒸馏（旧 SKILL.md 注入 prompt）
- ✅ 保留 `skill_name`（kebab-case）+ `description`（注入 frontmatter）+ `skill_md` 正文

### 5.3 蒸馏失败的降级

- LLM 返回非法 JSON → 重试 1 次（复用 agentscope model 的重试机制）
- 重试仍失败 → 经 `record_error` 回传原始事件仍保留在落盘的 trace，用户可重试
- **不**自动降级为"事件列表转 markdown"（那种产物对 Agent 无价值）

### 5.4 文件归属

| 新文件（agent-core 内） | 参考自 Browser-BC |
|---|---|
| `agent-core/recorder/atomizer.py` | `harness/atomizer.py` |
| `agent-core/recorder/distiller.py` | `harness/distiller.py`（简化版 prompt） |
| `agent-core/recorder/event_utils.py` | `harness/event_utils.py`（事件→文本摘要） |
| `agent-core/recorder/types.py` | 本地定义 `TraceEnvelope`/`Segment`/`DistillResult` |
| `agent-core/recorder/installer.py` | `harness/install.py`（简化版） |
| `agent-core/recorder/__init__.py` | 模块导出 |

### 5.5 模型选择

复用现有 `agent/model.py` 的工厂，蒸馏用**与 BrowserAgent 相同的 LLM**（config.yaml 的 `model` 配置），不单独配蒸馏模型——保持配置最简。未来如需分离，在 config 加 `recorder.distill_model` 字段即可（扩展点）。

## 6. 安装层 + 实时生效

### 6.1 实时生效机制（基于 agentscope 源码确认）

agentscope 的 `LocalSkillLoader` 本身就是**按需实时扫描**的：
- `list_skills()` 每次调用都重新 `os.walk` 扫描目录
- 按 SKILL.md 的 mtime 做缓存失效——新增/修改文件都会被自动检测
- `Toolkit` 把 loader 存下来按需调用，每次构建 prompt / SkillViewer 触发时枚举

**结论**：只要新 SKILL.md 落在已注册的 `agent-core/skills/` 目录下，下一次 Agent 构建提示词时就会自动扫到，**零额外代码、无需重启**。

### 6.2 安装层（`recorder/installer.py`）

```python
# 写入 agent-core/skills/<skill_name>/SKILL.md（已有 loader 覆盖该目录）
skill_dir = Path(config.skills_dirs[0]) / result.skill_name
skill_dir.mkdir(parents=True, exist_ok=True)
(skill_dir / "SKILL.md").write_text(
    f"---\nname: {result.skill_name}\n"
    f"description: {result.description}\n---\n\n{result.skill_md}",
    encoding="utf-8",
)
```

- **命名冲突**：目录已存在则追加 `-2`/`-3` 后缀（不做智能合并，初版最简）
- **原始 trace 留档**：`agent-core/skills/<skill_name>/_source_trace.json`（`_` 前缀，`LocalSkillLoader` 只认 `SKILL.md`，不会误读）
- **写完即生效**：下一次 `list_skills()` 自动扫到，无需 reload、无需重建 Toolkit、无需重启后端

### 6.3 推送 `skills_list` 刷新前端

虽然 loader 会自动扫到新技能，但前端 SidePanel 的「✦ 技能」popover 列表是在 WS 握手时推送一次的。新技能生成后，主动再推一次 `skills_list` 让前端列表刷新——用户录制完立刻能在技能按钮里看到新技能。

**调整 `record_done` 的处理**：蒸馏安装完成后，后端连续推送：
1. `skills_list`（重新调 `BrowserAgent.list_skills()` 拿最新列表）
2. `record_done`（带 `skill_name`，前端提示「立即可用」）

## 7. UI 交互

在现有 `ChatView.tsx` 的「✦ 技能」按钮旁，新增「● 录制」按钮。三态状态机：

```
idle ──click──▶ recording ──click──▶ distilling ──LLM完成──▶ done
  ▲                                              │
  └──────────────── discard ◀──────────────────┘
```

### 7.1 各状态 UI

| 状态 | 按钮表现 | 附加 UI |
|---|---|---|
| `idle` | 「● 录制」灰色圆点 | 无 |
| `recording` | 「● 录制中」红色闪烁圆点 + 计时器（mm:ss） | toast：「正在录制，操作目标页面即可」 |
| `distilling` | 按钮禁用 + spinner | toast 实时显示 `record_distill_progress` 的 stage 文案 |
| `done` | 恢复 `idle` | 成功提示「✓ 技能 `{name}` 已生成，立即可用」 |

### 7.2 停止录制

- 二次点击「● 录制中」按钮 → 弹一个轻量确认（输入框预填 label，如「搜索商品并加入购物车」）→ 确认后发送 `record_stop`
- 确认框提供「丢弃」选项 → 清空内存缓冲，不发送任何消息

### 7.3 关键交互细节

- 录制期间，SidePanel 的聊天功能**保持可用**（两者职责正交，用户可一边录一边问 Agent）
- 录制期间若切换标签页 → 暂停事件捕获（只录激活 tab），切回继续
- 录制期间扩展图标显示红色 badge（`●`），与 Browser-BC 一致

### 7.4 前端状态管理

```typescript
// chrome-extension/src/hooks/useRecorder.ts（新增）
type RecorderStatus = 'idle' | 'recording' | 'distilling' | 'done';
interface RecorderState {
  status: RecorderStatus;
  trace_id: string | null;
  startedAt: number | null;     // 计时用
  eventCount: number;           // 已捕获事件数
  distillStage: string | null;  // 'atomize' | 'distill' | 'install'
  lastSkill: { name: string; path: string } | null;
}
```

- 通过 `chrome.runtime.sendMessage` 与 background 通信（start/stop/cancel）
- 监听 background 广播的 `record_*` 消息更新状态
- 计时器用 `setInterval`，基于 `startedAt` 计算

## 8. 错误处理与边界

### 8.1 录制中的异常

| 场景 | 处理 |
|---|---|
| 用户关闭/刷新被录制 tab | content script 卸载前 `beforeunload` 触发 flush，把缓冲事件发回 background；若 tab 已销毁，background 检测到 tab 不存在 → 自动 `record_stop` 并提示用户 |
| 用户切换到非录制 tab | 暂停捕获（只录原激活 tab），切回继续；不跨 tab 录制 |
| Service Worker 崩溃重启 | 照搬 Browser-BC：从 IndexedDB 查 `status='recording'` 的行恢复 `activeRecordSession`，badge 重新点亮 |
| 事件捕获异常（单个 recorder 报错） | 单个 recorder 报错不阻断其他 recorder；log 后继续，录制不中断 |

### 8.2 传输异常

| 场景 | 处理 |
|---|---|
| WS 断开（录制中） | 事件继续在 background 内存缓冲（不丢），WS 重连后继续发送；缓冲超 5000 条时落盘 IndexedDB 防内存膨胀 |
| `record_stop` 时 WS 断开 | 提示「上传失败，录制已保存在本地」，重连后提供「重试上传」按钮 |
| 后端 `record_event` 收到未知 `trace_id` | 忽略并 log（可能是重连后的过期消息） |

### 8.3 蒸馏异常

| 场景 | 处理 |
|---|---|
| LLM 返回非法 JSON | 重试 1 次（复用 agentscope model 重试）；仍失败 → `record_error`，保留 trace 文件供重试 |
| LLM 超时/网络错误 | 同上，`record_error` + 保留 trace |
| 切片后段数为 0（全是噪音） | `record_error` stage=`atomize`，提示「未捕获到有效操作，请重新录制」 |
| `skill_name` 非法（含路径分隔符等） | 安装前 sanitize：只保留 `[a-z0-9-]`，非法字符转 `-`；为空则回退 `recorded-skill-{timestamp}` |
| 安装目录写权限失败 | `record_error` stage=`install` |

### 8.4 蒸馏重试机制（利用保留的 trace）

因 `_source_trace.json` 已落盘，失败的蒸馏可重试：
- 前端在 `record_error` 的 toast 里提供「重试蒸馏」按钮
- 发送 `record_redistill`（带 `trace_id`）→ 后端读 `_source_trace.json` → 重跑 atomize + distill
- 这是初版就提供的最小闭环，不依赖未来的 bucket 归并

### 8.5 并发与取消

| 场景 | 处理 |
|---|---|
| 录制中又点「录制」 | 忽略（状态机已是 recording） |
| 蒸馏中又发起录制 | 允许（蒸馏是独立 task，录制开新 session，互不干扰）；但同一时刻最多一个录制 session |
| 蒸馏中关闭 SidePanel / WS 断开 | 蒸馏 task 在后端继续跑完，trace 和 SKILL.md 已持久化；WS 在线则推送通知，离线则结果已落盘不丢失 |

## 9. 配置变更

`agent-core/config.yaml` 新增可选配置：

```yaml
# 录制蒸馏配置（均有默认值，可不配置）
recorder:
  # 蒸馏用的模型（不配则复用 BrowserAgent 的 model）
  distill_model: null
  # 单批上传事件数上限
  batch_size: 500
  # 内存缓冲落盘阈值
  buffer_flush_threshold: 5000
```

`config_loader.py` 需相应扩展读取逻辑（向后兼容：未配置时用默认值）。

## 10. 文件清单总览

### 前端新增（chrome-extension）

| 文件 | 作用 |
|---|---|
| `src/capture/types.ts` | 事件数据结构 |
| `src/capture/action-recorder.ts` | DOM 事件捕获 |
| `src/capture/selector.ts` | 稳定选择器生成 |
| `src/capture/mutation-summary-recorder.ts` | DOM 变更摘要 |
| `src/capture/redactor.ts` | 隐私脱敏 |
| `src/capture/recorder.ts` | 录制编排（start/stop/flush） |
| `src/entrypoints/recorder.content.ts` | 动态注入的 content script 入口 |
| `src/hooks/useRecorder.ts` | 前端录制状态管理 |
| `src/types/index.ts`（改） | 新增 `record_*` 消息类型 |
| `src/entrypoints/background.ts`（改） | 新增 `record_*` 路由 + 注入逻辑 |
| `src/components/ChatView.tsx`（改） | 新增录制按钮 + 三态 UI |

### 后端新增（agent-core）

| 文件 | 作用 |
|---|---|
| `recorder/__init__.py` | 模块导出 |
| `recorder/types.py` | `TraceEnvelope`/`Segment`/`DistillResult` |
| `recorder/atomizer.py` | 轨迹切片 |
| `recorder/distiller.py` | LLM 蒸馏 → SKILL.md |
| `recorder/event_utils.py` | 事件→文本摘要 |
| `recorder/installer.py` | 写入 skills 目录 |
| `server.py`（改） | 新增 `record_*` 处理 |
| `config.yaml`（改） | 新增 `recorder` 配置 |
| `config_loader.py`（改） | 读取 `recorder` 配置 |

## 11. 扩展接口（为未来归并预留）

虽然初版不实现 classify/bucket，但数据结构和模块边界已为其预留：

- `Segment` 含 `bucket_id` / `capability` 字段（初版置空）
- `recorder/` 模块职责单一，未来可在 `atomizer` 和 `distiller` 之间插入 `classifier.py` 和 `bucketer.py`
- `installer.py` 的冲突处理是简单后缀，未来可改为「同 bucket 增量更新」
- config 的 `recorder.distill_model` 为分离蒸馏模型预留
