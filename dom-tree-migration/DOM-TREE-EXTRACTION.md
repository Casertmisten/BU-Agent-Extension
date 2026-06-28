# DOM 树提取与脱水技术文档

> 本文档详细记录 page-agent 项目中 DOM 树处理的完整技术实现，供迁移到其他项目参考。
> 源码位置：`packages/page-controller/src/dom/`

## 目录

- [1. 架构总览](#1-架构总览)
- [2. 核心数据结构](#2-核心数据结构)
- [3. DOM 提取引擎](#3-dom-提取引擎)
  - [3.1 入口与配置](#31-入口与配置)
  - [3.2 递归遍历 buildDomTree](#32-递归遍历-builddomtree)
  - [3.3 节点过滤](#33-节点过滤)
  - [3.4 可见性判断](#34-可见性判断)
  - [3.5 交互性判断](#35-交互性判断)
  - [3.6 遮挡检测](#36-遮挡检测)
  - [3.7 高亮分配与去重](#37-高亮分配与去重)
  - [3.8 可滚动元素检测](#38-可滚动元素检测)
  - [3.9 视口裁剪](#39-视口裁剪)
  - [3.10 Shadow DOM 与 iframe](#310-shadow-dom-与-iframe)
  - [3.11 高亮覆盖层](#311-高亮覆盖层)
  - [3.12 性能优化](#312-性能优化)
- [4. 脱水序列化层](#4-脱水序列化层)
  - [4.1 flatTreeToString](#41-flattreetostring)
  - [4.2 属性处理策略](#42-属性处理策略)
  - [4.3 语义标签保留](#43-语义标签保留)
  - [4.4 新元素标记](#44-新元素标记)
- [5. 索引映射](#5-索引映射)
- [6. 页面状态采集](#6-页面状态采集)
- [7. 完整数据流](#7-完整数据流)
- [8. 迁移指南](#8-迁移指南)

---

## 1. 架构总览

DOM 处理分为三层，各层职责单一、可独立迁移：

```
┌─────────────────────────────────────────────────────────┐
│  调用层  PageController.ts                                │
│  编排流程：updateTree() / getBrowserState() / clickElement │
└──────────────────────────┬──────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────┐
│  脱水层  dom/index.ts  (TypeScript)                       │
│  FlatDomTree → LLM 文本 + 索引映射 + 高亮清理              │
└──────────────────────────┬──────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────┐
│  引擎层  dom/dom_tree/index.js  (纯 JS, 移植自 browser-use) │
│  Live DOM → FlatDomTree                                  │
└─────────────────────────────────────────────────────────┘
```

**关键设计决策**：

- 引擎层是**单文件纯 JS**，无外部依赖，可直接注入浏览器执行环境（类似 Playwright 的 `page.evaluate`）
- 数据结构用**扁平 map** 而非嵌套树，存储高效、按 index 查找 O(1)
- 默认 `viewportExpansion = -1`（全页模式），跳过昂贵的遮挡检测换取速度
- 交互性判断的**核心信号是 CSS cursor**，其次是标签/role/事件监听器

---

## 2. 核心数据结构

```typescript
// 扁平化 DOM 树，用 map 存储所有节点，rootId 指向根
interface FlatDomTree {
  rootId: string              // 根节点 ID（通常是 body）
  map: Record<string, DomNode> // id → 节点
}

// 三种节点类型
type DomNode = TextDomNode | ElementDomNode | InteractiveElementDomNode

// 文本节点
interface TextDomNode {
  type: 'TEXT_NODE'
  text: string
  isVisible: boolean
}

// 普通元素节点
interface ElementDomNode {
  tagName: string
  attributes?: Record<string, string>
  children?: string[]              // 子节点 ID 列表
  isVisible?: boolean
  isTopElement?: boolean           // 是否未被遮挡
  isInViewport?: boolean
  isNew?: boolean                  // 是否本次新出现的元素
  isInteractive?: false            // 普通元素为 false
  highlightIndex?: number
  extra?: Record<string, any>      // 扩展数据（如滚动信息）
}

// 可交互元素节点（带 DOM 引用）
interface InteractiveElementDomNode {
  // ...同 ElementDomNode
  isInteractive: true
  highlightIndex: number           // LLM 操作用的序号
  ref: HTMLElement                 // ⚠️ 直接持有 DOM 引用，用于后续操作
}
```

**为什么用扁平 map**：嵌套树在序列化/反序列化、按 index 查找时都需要递归遍历；扁平 map 让所有节点 O(1) 可达，`children` 用 ID 数组维持层级关系。

**`ref` 字段的代价**：直接持有 `HTMLElement` 引用意味着 `FlatDomTree` **不可跨执行上下文传递**（不能序列化）。这是有意为之——提取和操作必须在同一个 DOM 上下文中完成。迁移时需注意：如果跨 iframe 或跨进程，需要重新设计 ref 的存储方式（如用 xpath 或 selector）。

---

## 3. DOM 提取引擎

源文件：`dom/dom_tree/index.js`（约 1750 行，移植自 browser-use 0.5.9）

### 3.1 入口与配置

```javascript
export default (args) => {
  const {
    doHighlightElements,      // 是否创建视觉高亮 overlay
    focusHighlightIndex,      // -1 = 高亮全部；>=0 = 只高亮指定 index
    viewportExpansion,        // 视口扩展：-1=全页, 0=仅视口, 正数=扩展像素
    debugMode,
    interactiveBlacklist,     // 强制视为非交互的元素数组
    interactiveWhitelist,     // 强制视为可交互的元素数组
    highlightOpacity,         // 高亮填充透明度
    highlightLabelOpacity,    // 标签透明度
  } = args
  // ...
  const rootId = buildDomTree(document.body)
  return { rootId, map: DOM_HASH_MAP }
}
```

引擎内部维护两个关键全局状态：
- `DOM_HASH_MAP`：`{ id → nodeData }`，最终返回的 map
- `ID.current`：自增计数器，为每个节点分配唯一 ID
- `highlightIndex`：可交互元素的序号计数器，从 0 开始

### 3.2 递归遍历 buildDomTree

这是整个引擎的核心，采用 DFS 深度优先遍历：

```javascript
function buildDomTree(node, parentIframe = null, isParentHighlighted = false) {
  // 1. 快速拒绝检查
  // 2. 特殊处理 body 根节点
  // 3. 处理文本节点
  // 4. 处理元素节点：
  //    a. isElementAccepted 过滤
  //    b. 视口快速裁剪
  //    c. 构建 nodeData
  //    d. 可见性 / 交互性 / 高亮判断
  //    e. 递归处理子节点（含 iframe / shadow DOM / contenteditable）
  // 5. 分配 ID，存入 map，返回 ID
}
```

`isParentHighlighted` 参数用于**高亮去重**：如果父元素已获得 highlightIndex，子元素默认不再高亮，除非它是独立交互（详见 [3.7](#37-高亮分配与去重)）。这个状态在递归时向下传递。

### 3.3 节点过滤

**快速拒绝**（在 buildDomTree 开头）：

```javascript
// 跳过高亮容器自身
if (node.id === HIGHLIGHT_CONTAINER_ID) return null
// 自定义忽略标记
if (node.dataset?.browserUseIgnore === 'true') return null
if (node.dataset?.pageAgentIgnore === 'true') return null
// 无障碍隐藏
if (node.getAttribute('aria-hidden') === 'true') return null
```

**元素标签过滤** `isElementAccepted`：

```javascript
const alwaysAccept = new Set(['body','div','main','article','section','nav','header','footer'])
const leafElementDenyList = new Set(['svg','script','style','link','meta','noscript','template'])
// alwaysAccept 中的直接通过，denyList 中的直接拒绝，其余通过
```

**文本节点过滤**：空文本直接跳过；父元素是 `<script>` 的跳过。

### 3.4 可见性判断

有针对元素和文本节点的两套判断：

**元素可见性** `isElementVisible`（快速判断）：

```javascript
function isElementVisible(element) {
  const style = getCachedComputedStyle(element)
  return (
    element.offsetWidth > 0 &&
    element.offsetHeight > 0 &&
    style?.visibility !== 'hidden' &&
    style?.display !== 'none'
  )
}
```

用 `offsetWidth/Height` 而非 `getBoundingClientRect`，性能更好（不触发布局重排）。

**文本节点可见性** `isTextNodeVisible`（更精确）：

```javascript
// viewportExpansion === -1（全页模式）时：
//   只检查父元素的 checkVisibility（opacity + visibility CSS）
// 其他模式：
//   用 Range.getClientRects() 检查文本是否有可见矩形 + 在视口内 + 父元素可见
```

### 3.5 交互性判断

`isInteractiveElement` 是最复杂的函数，采用**多层启发式**，按信号强度从高到低：

```
1. 黑名单 / 白名单（最高优先级）
   ├─ interactiveBlacklist.includes(element) → false
   └─ interactiveWhitelist.includes(element) → true

2. CSS cursor 检测（核心信号！）
   └─ pointer / move / grab / text / cell / copy / ... 等 30+ 种交互光标 → true
   └─ not-allowed / no-drop / wait / progress → 后续判断中排除

3. 原生交互标签
   └─ a / button / input / select / textarea / details / summary / label / option ...
   └─ 排除 disabled / readonly / inert

4. contenteditable
   └─ element.isContentEditable || contenteditable="true" → true

5. ARIA role
   └─ button / menu / menuitem / checkbox / tab / slider / combobox / option ...

6. 启发式 class
   └─ classList.contains('button' | 'dropdown-toggle')
   └─ aria-haspopup="true"

7. 事件监听器（在浏览器中通常不可用）
   └─ window.getEventListeners (仅 Playwright/CDP 环境)
   └─ onclick / onmousedown 等内联属性（兜底）

8. 可滚动元素
   └─ isScrollableElement(element) → true
```

**cursor 检测是整个判断的灵魂**。因为现代前端框架（React/Vue）的事件绑定不会反映在 DOM 属性上，`onclick` 属性检测基本失效，但 CSS cursor 是框架主动设置的视觉交互提示，可靠性最高。

### 3.6 遮挡检测

`isTopElement` 判断元素是否被其他元素遮挡：

```javascript
function isTopElement(element) {
  // 全页模式直接返回 true（跳过昂贵检测）
  if (viewportExpansion === -1) return true

  // 1. 取元素的一个有效 rect 作为采样点
  // 2. 在中心点 + 左上角 + 右下角采样
  // 3. 对每个点调用 document.elementFromPoint(x, y)
  // 4. 从返回的元素向上遍历父链，看能否到达目标元素
  //    能到达 → 未被遮挡
}
```

**这是全引擎最昂贵的操作**，因为 `elementFromPoint` 会触发完整的 hit-testing。`viewportExpansion === -1` 跳过它是默认全页模式的核心性能优化。

> 迁移注意：如果你的场景必须精确判断遮挡（如弹窗内的元素），需要用 `viewportExpansion = 0`，但要接受性能下降。

### 3.7 高亮分配与去重

`handleHighlighting` 决定哪些可交互元素获得 `highlightIndex`：

```javascript
function handleHighlighting(nodeData, node, parentIframe, isParentHighlighted) {
  if (!nodeData.isInteractive) return false

  let shouldHighlight = false

  if (!isParentHighlighted) {
    // 父元素未被高亮 → 当前元素可以高亮
    shouldHighlight = true
  } else {
    // 父元素已被高亮 → 只有"独立交互"的子元素才高亮
    shouldHighlight = isElementDistinctInteraction(node)
  }

  if (shouldHighlight) {
    nodeData.isInViewport = isInExpandedViewport(node, viewportExpansion)
    if (nodeData.isInViewport || viewportExpansion === -1) {
      nodeData.highlightIndex = highlightIndex++  // 分配序号
      // ... 创建高亮 overlay
    }
  }
}
```

**去重逻辑**：假设有一个 `<button><span>文字</span><img/></button>`，button 被高亮后，span 和 img 默认不高亮（点击它们等价于点击 button）。只有当子元素是**独立交互**时才单独高亮。

**独立交互判断** `isElementDistinctInteraction`：

```javascript
// 以下情况子元素被视为独立交互：
// - iframe（跨文档边界）
// - a / button / input / select / textarea / summary / details / label / option / li
// - role: button / link / menuitem / radio / checkbox / tab / slider / combobox ...
// - contenteditable
// - data-testid / data-cy / data-test（测试属性）
// - onclick（属性或属性）
// - hasInteractiveAria（aria-expanded / aria-checked / aria-selected ...）
// - 事件监听器（click / mousedown / keydown ...）
// - isHeuristicallyInteractive（class 含 btn/clickable/menu + 在已知容器内）
// - 可滚动容器
```

### 3.8 可滚动元素检测

`isScrollableElement` 是项目相对 browser-use 新增的功能：

```javascript
function isScrollableElement(element) {
  // 1. 排除 inline / inline-block 元素
  // 2. 检查 overflow-x / overflow-y 是否为 auto / scroll
  //    或 scrollbar-width / scrollbar-gutter 信号
  // 3. 计算 scrollWidth - clientWidth 和 scrollHeight - clientHeight
  // 4. 阈值过滤：< 4px 视为不可滚动
  // 5. 计算四向可滚动距离并存入 extraData：
  //    { top, right, bottom, left }
}
```

可滚动元素会被视为可交互（获得 highlightIndex），LLM 可以对它执行滚动操作。滚动距离数据通过 `extra.scrollData` 传递到脱水文本中。

### 3.9 视口裁剪

通过 `viewportExpansion` 参数控制：

| 值 | 行为 | 适用场景 |
|---|---|---|
| `-1` | **全页**：不裁剪，所有元素都处理，跳过 `isTopElement` | 默认值，追求速度 |
| `0` | **仅视口**：只处理当前可见区域的元素 | 精确场景，大页面优化 |
| `>0` | **扩展视口**：视口四周扩展 N 像素 | 平衡方案 |

裁剪发生在两处：
1. `buildDomTree` 中对元素节点的**快速裁剪**（用 `getBoundingClientRect` 粗筛）
2. `isInExpandedViewport` 的**精确裁剪**（用 `getClientRects` 检查任意一个 rect 在视口内）

### 3.10 Shadow DOM 与 iframe

```javascript
// iframe：递归进入 iframe 的 document
if (tagName === 'iframe') {
  const iframeDoc = node.contentDocument || node.contentWindow?.document
  for (const child of iframeDoc.childNodes) {
    buildDomTree(child, node, false)  // parentIframe = 当前 iframe
  }
}

// Shadow DOM：递归进入 shadowRoot
if (node.shadowRoot) {
  nodeData.shadowRoot = true
  for (const child of node.shadowRoot.childNodes) {
    buildDomTree(child, parentIframe, nodeWasHighlighted)
  }
}

// contenteditable / 富文本编辑器（TinyMCE 等）
// 特殊处理，捕获格式化文本
```

**跨域 iframe**：`contentDocument` 访问会抛异常，被 catch 后跳过（仅 console.warn）。

### 3.11 高亮覆盖层

`highlightElement` 在页面上创建视觉标记，供用户/调试查看：

```javascript
function highlightElement(element, index, parentIframe) {
  // 1. 创建/获取固定容器 #playwright-highlight-container (z-index: 2147483640)
  // 2. 为元素的每个 clientRect 创建 overlay div（边框 + 半透明背景）
  // 3. 创建序号标签（定位在第一个 rect 的右上角）
  // 4. 注册 scroll/resize 监听（节流 16ms ~60fps）实时更新位置
  // 5. 返回清理函数，存入 window._highlightCleanupFunctions
}
```

**透明度可配置**：`highlightOpacity`（填充）和 `highlightLabelOpacity`（标签），默认 0.0 / 0.1，即只显示边框几乎不遮挡页面。

**清理机制**：所有清理函数存在全局数组，由上层的 `cleanUpHighlights()` 统一调用。

### 3.12 性能优化

引擎内置多层优化：

1. **DOM 缓存**（`DOM_CACHE`）：用 `WeakMap` 缓存 `getBoundingClientRect` / `getComputedStyle` / `getClientRects` 结果，同一次提取内不重复计算。提取完成后 `clearCache()`。

2. **快速拒绝优先**：廉价检查（标签名、dataset）在昂贵检查（`elementFromPoint`）之前，尽早 return null。

3. **cursor 短路**：交互性判断中，cursor 命中直接 return true，跳过后续所有检查。

4. **全页模式**（`viewportExpansion = -1`）：跳过 `isTopElement`（最昂贵）和精确视口检测。

5. **XPath 缓存**：`WeakMap` 缓存 XPath 计算（虽然项目已注释掉 xpath 生成，但缓存逻辑保留）。

> 迁移提示：DOM 缓存是**单次提取有效**的。跨多次提取需要重新构建，因为 DOM 可能已变化。WeakMap 会自动回收被移除节点的缓存。

---

## 4. 脱水序列化层

源文件：`dom/index.ts`。将 `FlatDomTree` 转换为 LLM 可读的文本格式。

### 4.1 flatTreeToString

核心序列化函数，输出格式示例：

```text
Current Page: [页面标题](https://example.com)
Page info: 1920x1080px viewport, 1920x3000px total page size, 0.0 pages above, 1.8 pages below, 2.8 total pages, at 0% of page

Interactive elements from top layer of the current page (full page):

[Start of page]
[0]<a aria-label=首页 href=/> 首页 />
\t[1]<input type=text placeholder=搜索 />
[2]<a role=button href=/docs> 文档 />
\t*[3]<button data-action=submit> 提交 />
无需后端
\tAI 理解页面并自动操作。
[4]<div data-scrollable="top=0, bottom=800" />
... 1620 pixels below (1.8 pages) - scroll to see more ...
```

**格式规则**：

| 元素 | 格式 | 说明 |
|---|---|---|
| 可交互元素 | `[index]<tag attr=v>text />` | index 供 LLM 引用操作 |
| 新可交互元素 | `*[index]<tag ...>` | `*` 标记本次新出现 |
| 可滚动元素 | `data-scrollable="top=X, ..."` | 附加滚动距离 |
| 普通文本 | 直接输出 | 无方括号前缀 |
| 缩进 | `\t` × depth | 表示父子层级 |

**文本节点的过滤规则**（避免冗余）：

```javascript
// 文本节点只在以下条件全满足时输出：
// 1. 没有带 highlightIndex 的祖先（否则文本已被父元素的 >text 包含）
// 2. 父元素可见（isVisible）
// 3. 父元素未被遮挡（isTopElement）
```

**getAllTextTillNextClickableElement**：收集元素内部所有文本，直到遇到下一个可交互子元素为止。用于填充可交互元素的 `>text` 部分，让 LLM 知道按钮的文字内容。

### 4.2 属性处理策略

默认包含的属性（`DEFAULT_INCLUDE_ATTRIBUTES`）：

```javascript
[
  'title', 'type', 'checked', 'name', 'role', 'value', 'placeholder',
  'data-date-format', 'alt', 'aria-label', 'aria-expanded', 'data-state',
  'aria-checked',
  'id', 'for',              // 表单关联
  'target',                 // 链接跳转方式
  'aria-haspopup', 'aria-controls', 'aria-owns',  // 下拉菜单
  'contenteditable',
]
```

支持 glob 通配符（`data-*`）匹配属性名。

**属性去重策略**（减少 token 消耗）：

```javascript
// 1. 值去重：多个属性值相同（>5字符）则只保留第一个
//    如 aria-label="提交" 和 title="提交" → 只保留 aria-label
// 2. role 与 tagName 相同则去除 role
//    如 <button role="button"> → 去掉 role
// 3. aria-label / placeholder / title 与文本内容相同时去除
//    如 <button aria-label="提交">提交</button> → 去掉 aria-label
// 4. 文本截断：属性值超过 20 字符截断为 "前20字..."
```

### 4.3 语义标签保留

`keepSemanticTags` 开启时，即使不可交互也会保留语义标签作为上下文：

```javascript
const SEMANTIC_TAGS = new Set(['nav', 'menu', 'header', 'footer', 'aside', 'dialog'])
// 输出形如：
// <nav>
//     [0]<a href=/>首页 />
//     [1]<a href=/docs>文档 />
// </nav>
```

空标签会被自动移除（无子内容输出时不保留开闭标签）。

> 文档注释提到此功能可能对 LLM 造成困惑（与页面滚动结合时），需谨慎使用。

### 4.4 新元素标记

```javascript
const newElementsCache = new WeakMap<HTMLElement, string>()

// 提取时遍历所有可交互元素
for (const nodeId in elements.map) {
  const node = elements.map[nodeId]
  if (node.isInteractive && node.ref) {
    if (!newElementsCache.has(node.ref)) {
      newElementsCache.set(node.ref, currentUrl)
      node.isNew = true  // 标记为新元素
    }
  }
}
```

序列化时新元素前缀 `*`，帮助 LLM 关注页面变化。**局限**：用 DOM 引用做判断，元素被删除重建后会被误判为新元素（注释中提到 browser-use 用 hash 方案更可靠）。

---

## 5. 索引映射

两个映射函数支撑"按序号操作"的核心机制：

```typescript
// highlightIndex → 可交互节点（含 DOM ref）
function getSelectorMap(flatTree): Map<number, InteractiveElementDomNode>

// 从序列化文本反向解析 highlightIndex → 文本行（用于操作日志）
function getElementTextMap(simplifiedHTML): Map<number, string>
```

**操作流程**（在 actions.ts 中）：

```typescript
function getElementByIndex(selectorMap, index): HTMLElement {
  const interactiveNode = selectorMap.get(index)  // O(1) 查找
  return interactiveNode.ref                       // 直接拿 DOM 引用
}

// 然后 clickElement(element) / inputText(element, text) / scroll(element)
```

这套设计让 LLM 只需返回 `[index, action]`，系统通过 selectorMap 直接定位 DOM 元素操作，无需重新查询。

---

## 6. 页面状态采集

`getPageInfo` 采集页面尺寸和滚动信息，供 LLM 理解"还有多少内容未可见"：

```typescript
function getPageInfo() {
  return {
    viewport_width, viewport_height,    // 视口尺寸
    page_width, page_height,            // 整页尺寸
    scroll_x, scroll_y,                 // 滚动位置
    pixels_above, pixels_below,         // 上下未可见像素
    pages_above, pages_below, total_pages,  // 换算成页数
    current_page_position,              // 0~1 滚动百分比
  }
}
```

PageController 将其组装为人类可读的提示：

```text
Page info: 1920x1080px viewport, 1920x3000px total page size,
0.0 pages above, 1.8 pages below, 2.8 total pages, at 0% of page
```

这帮助 LLM 判断是否需要滚动来查看更多元素。

---

## 7. 完整数据流

```
┌──────────────┐
│  Live DOM    │
└──────┬───────┘
       │ buildDomTree() DFS 遍历
       │ ├─ 过滤（标签/data-attr/aria-hidden）
       │ ├─ 可见性（offsetWidth + computedStyle）
       │ ├─ 交互性（cursor > tag > role > 事件）
       │ ├─ 遮挡检测（elementFromPoint 采样）
       │ ├─ 高亮分配（父子去重）
       │ └─ 可滚动检测
       ▼
┌──────────────────┐
│  FlatDomTree     │  { rootId, map: {id → node} }
│  (扁平 map)       │  可交互节点含 highlightIndex + ref
└──────┬───────────┘
       │
       ├─→ flatTreeToString() ──→ simplifiedHTML (缩进文本)
       │                         可交互: [index]<tag>text />
       │                         文本: 直接输出
       │                         新元素: *[index]
       │
       ├─→ getSelectorMap() ────→ Map<highlightIndex, node>
       │                         O(1) 按序号查找元素
       │
       └─→ getElementTextMap() ─→ Map<highlightIndex, 文本行>
                                   操作日志用
       │
       ▼
┌──────────────────────┐
│  getBrowserState()   │  拼接 header + content + footer
│  header: 页面信息     │  ├─ title + url
│  content: 简化HTML    │  ├─ viewport/page 尺寸
│  footer: 滚动提示     │  └─ 滚动位置提示
└──────────┬───────────┘
           │
           ▼
┌──────────────────┐
│      LLM         │  返回 action plan: { index, action, args }
└──────────┬───────┘
           │
           ▼
┌──────────────────────┐
│  clickElement(index) │  selectorMap.get(index) → ref → 操作
│  inputText(index)    │
│  scroll(index)       │
└──────────────────────┘
```

---

## 8. 迁移指南

### 8.1 最小迁移（仅提取 + 脱水）

只需三个文件，无外部依赖：

```
dom/dom_tree/index.js   # 提取引擎（纯 JS）
dom/dom_tree/type.ts    # 类型定义（可选，迁移到 JS 项目可删）
dom/index.ts            # 脱水 + 映射 + 高亮清理
```

**关键依赖**：仅依赖浏览器全局 API（`document` / `window` / `getComputedStyle` / `elementFromPoint` 等），无 npm 包。

### 8.2 迁移检查清单

**环境要求**：

- [ ] 能在目标页面执行 JS（浏览器扩展 content script / Playwright evaluate / 注入脚本）
- [ ] 需要访问 `document.body`、`getComputedStyle`、`elementFromPoint`
- [ ] 如需跨 iframe，需能访问 `contentDocument`（同源）

**必须修改的部分**：

- [ ] `dom/index.ts` 末尾的全局事件监听（`window.addEventListener('popstate')` 等）——这是为 content script 设计的，迁移到其他环境可能不需要
- [ ] `highlightElement` 中的 `window._highlightCleanupFunctions` 全局变量——按你的环境改用模块级变量
- [ ] `getFlatTree` 中的 `newElementsCache` WeakMap ——如果要跨页面追踪新元素，需改为持久化存储

**可能需要调整的配置**：

- [ ] `viewportExpansion`：默认 -1（全页）。如果你的页面弹窗多需精确遮挡检测，改为 0
- [ ] `includeAttributes`：根据目标网站调整需要暴露给 LLM 的属性
- [ ] `SEMANTIC_TAGS`：根据目标网站的 HTML 习惯调整
- [ ] `highlightOpacity` / `highlightLabelOpacity`：视觉调试用，生产可设为 0

### 8.3 性能调优建议

**大页面卡顿**：

```javascript
// 方案1：启用视口裁剪（牺牲全页覆盖）
getFlatTree({ viewportExpansion: 0 })

// 方案2：用黑名单排除已知无关区域
getFlatTree({ interactiveBlacklist: [document.querySelector('.ad-container')] })
```

**可交互元素过多（LLM token 爆炸）**：

```javascript
// 减少暴露的属性
getFlatTree({ includeAttributes: ['aria-label', 'role'] })  // 只保留关键属性

// 或在 flatTreeToString 后做二次截断
```

**遮挡检测慢**：这是 `elementFromPoint` 固有开销，全页模式（`-1`）是唯一有效优化。如必须精确检测，考虑限制检测深度或对特定容器单独检测。

### 8.4 与 browser-use 的差异

本项目相对 browser-use 0.5.9 的改动（搜索源码中的 `@edit` 标记）：

| 改动 | 说明 |
|---|---|
| 直接 DOM ref | `nodeData.ref = node`，操作时无需重新查询 |
| 黑白名单 | `interactiveBlacklist` / `interactiveWhitelist` 运行时控制 |
| 可调透明度 | `highlightOpacity` / `highlightLabelOpacity` |
| 可滚动检测 | 新增 `isScrollableElement`，可滚动元素获高亮 |
| extra 字段 | `nodeData.extra` 存储扩展数据（滚动距离等）|
| 去除 xpath | 注释掉 xpath 生成，减少开销 |
| aria-hidden 排除 | `aria-hidden="true"` 的元素整棵跳过 |
| 交互属性保证 | 可交互元素即使未通过 candidate 检查也补充属性 |
| data-browser-use-ignore | 支持 `data-page-agent-ignore` 自定义忽略 |
| sampleRect 改进 | 过滤 0 面积 rect |

### 8.5 常见陷阱

1. **ref 不可序列化**：`FlatDomTree` 含 `HTMLElement` 引用，不能 `JSON.stringify` 或跨进程传递。如需传输，先 `flatTreeToString`。

2. **高亮残留**：如果 `cleanUpHighlights()` 未被调用，overlay 会残留在页面上。务必在每次 `updateTree` 前清理，或在页面卸载时清理。

3. **mask 干扰遮挡检测**：如果页面有 `pointer-events: auto` 的覆盖层（如本项目的 SimulatorMask），`elementFromPoint` 会命中它而非目标元素。提取前需临时设置 `pointer-events: none`。

4. **跨域 iframe 不可达**：`contentDocument` 访问跨域 iframe 会抛异常，引擎 catch 后静默跳过。这是浏览器安全限制，无法绕过。

5. **input.checked 不反映在属性中**：checkbox/radio 的 checked 状态是属性而非 HTML attribute，引擎做了特殊处理（`@workaround input.checked`）手动写入 `nodeData.attributes.checked`。

---

> **源码参考**：所有改动在 `dom/dom_tree/index.js` 中用 `@edit` 注释标记，可用 `grep '@edit'` 快速定位全部定制点。
