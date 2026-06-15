# 页面结构解析工具（parse_page）设计

> 日期：2026-06-14
> 状态：已认可，待生成实施计划
> 主题：将扁平的 `parse_dom` 升级为基于无障碍树（AX 树）语义化解析的 `parse_page`

## 背景与动机

现有 `parse_dom` 工具在 `content.js` 中用硬编码选择器
（`a, button, input, select, textarea, [role="button"], [onclick]`）抓取"可交互元素"，
返回扁平列表 `[{id, tag, text, type, placeholder}, ...]`。问题：

- **无层级**：LLM 拿不到页面结构，难以理解"这个按钮在哪个区域"。
- **信息稀疏**：只返回 5 个字段，丢掉了语义角色、关联 label、标题等。
- **靠选择器**：新增交互模式（自定义 ARIA widget）需改选择器，脆弱。

新工具 `parse_page` 通过**单遍 DOM 遍历同时推断无障碍树**，输出嵌套语义 JSON，
让 LLM 以接近浏览器无障碍树的视角理解页面。

## 设计决策（已与用户确认）

1. **解析位置**：纯 content.js 端，不用 CDP（避免"正在被调试"黄条）。
2. **AX 树来源**：从 DOM/ARIA 推断（ACCNAME 算法子集 + 语义标签映射）。
3. **清洗策略**：AX 树主导，输出 `{role, name, id?, children?}`。
4. **打标**：仅可交互节点赋 `agent-xx`；所有 AX 节点都进 JSON。
5. **体积控制**：轻量清洗（文本截断 ≤200 字、跳过装饰/隐藏节点），不设硬上限。
6. **方案**：A —— 单遍 DOM 遍历，AX 树与 DOM 树同构构造。
7. **切换**：config.yaml 的 `browser.dom_strategy`（`ax`/`flat`），默认 `ax`。
8. **工具命名**：Agent 侧统一叫 `parse_page`，切换对 LLM 透明。

## §1 总体架构与数据流

```
ParsePage 工具 (Python, ToolBase)
  └─ conn.send_action({action: "parse_page" | "parse_dom"})   # 由 config 决定
       └─ background.ts handleAction → executeInContentScript
            └─ content.js 收到 action
                 ├─ parse_page → parsePage() 单遍遍历，返回嵌套 AX 树
                 └─ parse_dom  → tagElements()（旧，扁平，不动）
```

**"并行"的含义**：单遍 DOM 遍历中同时抽取 DOM 信息与推断 AX 信息。
content.js 单线程无独立 I/O，不需要 `Promise.all`。

**切换机制（config 驱动）**：
- content.js 双 action 并存（被动响应，保留旧的零成本）。
- Agent 侧单工具 `ParsePage`，对外 name 永远是 `parse_page`。
- `ParsePage.__init__` 接收 `dom_strategy`，`__call__` 据此发对应 action。
- LLM 只看到一个工具，切换对它完全透明。

**下游兼容**：`get_element_info`/`click`/`input_text` 靠
`querySelector('[backend-id="agent-xx"]')` 定位，与 id 赋值方式无关。
只要 `parse_page` 写入的 id 仍是 `agent-00`/`agent-01`...，所有下游工具无需改动。

## §2 AX 树推断算法（content.js 核心）

### 2.1 Role 推断优先级

按顺序判断，命中即停：

| 优先级 | 来源 | 示例 |
|---|---|---|
| 0 | 根节点 | `<body>` → `WebArea`（name=`document.title`）；`<html>` 跳过，直接遍历子节点 |
| 1 | `role` 属性（验证为合法 ARIA role） | `<div role="navigation">` → `navigation` |
| 2 | HTML 语义标签映射 | `<button>`→button, `<a href>`→link, `<input type=email>`→textbox, `<nav>`→navigation, `<main>`→main, `<h1>`→heading, `<ul>`→list, `<li>`→listitem, `<img>`→image, `<select>`→combobox, `<textarea>`→textbox |
| 3 | 返回 null（不进 AX 树，但继续遍历子节点） | `<div>`/`<span>` 无 role 无语义 |

冷门标签（`<meter>`/`<output>` 等）默认当容器处理。

### 2.2 Accessible Name 计算（ACCNAME 子集）

按优先级取第一个非空值，截断 ≤200 字符：

1. `aria-labelledby` → 引用目标元素的 textContent
2. `aria-label` → 直接取值
3. 表单字段特例：`<label for=id>` 关联 或 包裹式 `<label>...</label>` 的 textContent
4. 元素自身：`alt`（img）/ `title` / `placeholder` / textContent
5. 都没有 → 空字符串

**根节点特例**：`WebArea` 的 name = `document.title`。

### 2.3 剪枝规则（不进入 AX 树）

任一满足即剪（但**继续遍历子节点**）：
- `role="none"`/`role="presentation"` 且无 name
- `aria-hidden="true"`
- 计算样式 `display:none`/`visibility:hidden`/`hidden` 属性
- role 为 null 且无 name 且无可进树子节点（纯空容器）

**子节点上浮**：`<div><button>登录</button></div>` 里 div 被剪，
但 button 挂到 div 父节点的 children 里，保持层级扁平化但不丢可交互元素。

### 2.4 可交互节点判定（决定是否赋 `agent-xx`）

进入 AX 树的节点中，role 属于以下集合才打标：
```
{button, link, textbox, searchbox, checkbox, radio,
 slider, spinbutton, switch, menuitem, menuitemcheckbox,
 menuitemradio, tab, option, combobox, treeitem}
```

### 2.5 单遍遍历算法（伪代码）

```js
function parsePage() {
  clearTags(); counter = 0;
  return buildAxNode(document.body);
}

function buildAxNode(el) {
  if (isHidden(el)) return null;
  const role = inferRole(el);     // 可能 null
  const name = computeName(el);   // 截断后

  const children = [];
  for (const child of el.children) {
    const built = buildAxNode(child);
    if (Array.isArray(built)) children.push(...built);  // 容器上浮
    else if (built) children.push(built);
  }

  if (role === null && !name && children.length === 0) return null;
  if (role === null && !name) return children.length ? children : null;

  const node = { role, name: name || undefined };
  if (isInteractive(role)) {
    const id = `agent-${String(counter++).padStart(2,'0')}`;
    el.setAttribute('backend-id', id);
    node.id = id;
  }
  if (children.length) node.children = children;
  return node;
}
```

## §3 输出 JSON 形态与示例

### 节点结构

```json
{
  "role": "string",
  "name": "string",
  "id": "agent-00",
  "children": [...]
}
```
顶层固定：`{ "role": "WebArea", "name": "页面标题", "children": [...] }`

### 示例对比

DOM：
```html
<main>
  <h1>用户登录</h1>
  <div class="form-wrap">
    <label for="email">邮箱</label>
    <input id="email" type="email" placeholder="请输入邮箱">
    <button type="submit">登录</button>
    <a href="/forgot">忘记密码</a>
  </div>
  <div style="display:none"><span>广告</span></div>
</main>
```

旧 `parse_dom`（扁平）：
```json
[
  {"id":"agent-00","tag":"input","text":"","type":"email","placeholder":"请输入邮箱"},
  {"id":"agent-01","tag":"button","text":"登录","type":"","placeholder":""},
  {"id":"agent-02","tag":"a","text":"忘记密码","type":"","placeholder":""}
]
```

新 `parse_page`（嵌套语义）：
```json
{
  "role": "WebArea",
  "name": "用户登录 - 示例站",
  "children": [
    {"role": "main", "children": [
      {"role": "heading", "name": "用户登录"},
      {"role": "textbox", "name": "邮箱", "id": "agent-00"},
      {"role": "button", "name": "登录", "id": "agent-01"},
      {"role": "link", "name": "忘记密码", "id": "agent-02"}
    ]}
  ]
}
```

## §4 config.yaml 设计

新增 `browser` 段：
```yaml
browser:
  dom_strategy: ${DOM_STRATEGY:-ax}   # "ax"=新版, "flat"=旧版
```

- 默认 `ax`；环境变量 `DOM_STRATEGY=flat` 可覆盖。
- `config_loader.py` 无需改动（已把 config 当 dict 加载）。
- `create_browser_tools` 已接收 config，把 `config["browser"]["dom_strategy"]`
  透传给 `ParsePage` 构造函数。
- 容错：`browser` 段缺失或未填时，`ParsePage.__init__` 默认 `"ax"`。

## §5 错误处理与边界

| 情况 | 处理 |
|---|---|
| `document.body` 不存在（`chrome://` 等） | 返回 `{role:"WebArea", name:"", children:[]}`，不抛错 |
| 循环 DOM / shadow DOM | 不穿透 shadow DOM（YAGNI）；visited Set 防御 |
| 超大页面（几万节点表格） | 轻量清洗已剪大部分；不设硬上限 |
| `aria-labelledby` 引用不存在的 id | 该优先级返回空，降级到下一优先级 |
| `<input>` 无任何 name 来源 | name 为空，节点仍进树（role=textbox 有语义价值） |
| `getComputedStyle` 性能 | 每节点只算一次，数千节点可接受 |
| content.js 注入失败/无响应 | 复用现有超时和 lastError 处理 |

**backend-id 一致性**：`parse_page` 和 `parse_dom` 开头都调 `clearTags()` 清理旧标记，
保证干净；id 格式统一 `agent-00`/`agent-01`...。

## §6 测试策略

### Agent 侧（Python，`tests/test_tools.py`）
1. `ParsePage` 在 `dom_strategy="ax"` 时发 `parse_page` action
2. `dom_strategy="flat"` 时发 `parse_dom` action
3. 默认（无 config）= `ax`
4. 工具清单完整性测试更新（13 → 14 个工具，name 唯一）
5. `ParsePage.is_read_only=True`、`input_schema` 已声明

### content.js 侧
通过 `window.__BU_AGENT__.parsePage` 暴露，测：
1. 简单登录页 → 输出嵌套 AX 树（对应 §3 示例）
2. 隐藏节点（`display:none`/`aria-hidden`）被剪枝
3. `<div>` 容器被剪但子节点上浮
4. 可交互节点有 `agent-xx`，纯文本节点无
5. accessible name 优先级（aria-label > label > textContent）
6. `backend-id` 属性确实写到 DOM 上

### 集成
手动在真实浏览器验证一次：AX 树结构正确、下游 click 能定位到
`parse_page` 标记的元素。

## 涉及文件清单

| 文件 | 改动 |
|---|---|
| `chrome-extension/public/content/content.js` | 新增 `parsePage()` + AX 推断辅助函数 + action 分支 + 暴露 |
| `chrome-extension/src/entrypoints/background.ts` | `parse_page` 加入 content script action 列表 |
| `chrome-extension/src/types/index.ts` | `ContentMessage.action` 联合类型加 `'parse_page'` |
| `chrome-extension/src/components/EventCards.tsx` | 图标/文案映射加 `parse_page` |
| `agent-core/browser/tools.py` | 新增 `ParsePage(ToolBase)`；工厂按 config 注册（替代 `ParseDom`） |
| `agent-core/config.yaml` | 新增 `browser.dom_strategy` |
| `agent-core/tests/test_tools.py` | 新增 `ParsePage` 测试；更新工具清单断言 |
| content.js 测试（如存在） | 新增 `parsePage` 用例 |
