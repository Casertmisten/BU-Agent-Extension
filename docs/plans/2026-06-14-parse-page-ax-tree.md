# 页面结构解析工具（parse_page）实施计划

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 将扁平 `parse_dom` 升级为基于无障碍树（AX 树）语义化解析的 `parse_page`，通过 config 切换策略。

**Architecture:** content.js 单遍遍历 DOM 同时推断 AX 树（role + accessible name），输出嵌套 JSON `{role, name, id?, children?}`，仅给可交互节点赋 `agent-xx`。Agent 侧单工具 `ParsePage`，按 `config["browser"]["dom_strategy"]` 决定发 `parse_page` 还是旧 `parse_dom` action，对 LLM 透明。

**Tech Stack:** Python（agentscope ToolBase, pytest-asyncio）/ 原生 JS（content script, vitest+jsdom）

**设计文档：** `docs/plans/2026-06-14-parse-page-ax-tree-design.md`

**关键约束（务必遵守）：**
- `parse_dom`（旧）**完全不动**，content.js 里保留。
- Agent 侧 `ParseDom` 类**删除**，被 `ParsePage` 取代（统一 name=`parse_page`）。
- `agent-xx` id 格式不变（下游 click/input_text 依赖）。
- 默认策略 `ax`；`flat` 为 fallback。
- 所有命令在 `agent-core/` 下用 `.venv/bin/python -m pytest`、在 `chrome-extension/` 下用 `npx vitest`。

**已知环境问题：** `chrome-extension/node_modules/.bin/vitest` 被删除（见 git status），且 `test/content.test.js` 导入路径 `'../content/content.js'` 实际文件在 `public/content/content.js`。content.js 测试**当前无法运行**。本计划 Task 1 先修复此问题，后续 content.js 任务才能 TDD。

---

### Task 1: 修复 content.js 测试环境（前置阻塞项）

**Files:**
- Modify: `chrome-extension/test/content.test.js:2`（导入路径）
- Restore: `chrome-extension/node_modules/.bin/vitest`（重装依赖）

**Step 1: 重装 vitest 依赖**

Run（在 `chrome-extension/` 下）:
```bash
npm install
```
Expected: `.bin/vitest` 恢复。

**Step 2: 修复导入路径**

把 `chrome-extension/test/content.test.js` 第 2 行：
```js
import '../content/content.js';
```
改为：
```js
import '../public/content/content.js';
```

**Step 3: 运行现有 content 测试，确认基线通过**

Run（在 `chrome-extension/` 下）:
```bash
npx vitest run test/content.test.js
```
Expected: 现有用例全部 PASS（若 tagElements 等用例因 DOM 变化失败，记录但不改——本任务只修环境）。

**Step 4: Commit**

```bash
git add chrome-extension/test/content.test.js chrome-extension/package-lock.json
git commit -m "fix(content-test): 修正导入路径并恢复 vitest 依赖"
```

---

### Task 2: content.js — AX 推断辅助函数（role + name + 剪枝）

本任务实现纯函数，不接 action 路由，全部可单测。

**Files:**
- Modify: `chrome-extension/public/content/content.js`（在 `tagElements` 之前新增 AX 推断函数）
- Test: `chrome-extension/test/content.test.js`（新增 `describe('AX inference')` 块）

**Step 1: 写失败测试（role 推断 + name 计算 + 剪枝）**

在 `test/content.test.js` 末尾追加：

```js
import {
  inferRole, computeName, isHidden, isInteractive,
} from '../public/content/ax-helpers.js';

describe('AX inference', () => {
  beforeEach(() => { document.body.innerHTML = ''; });

  describe('inferRole', () => {
    it('显式 role 属性优先', () => {
      document.body.innerHTML = '<div role="navigation"></div>';
      expect(inferRole(document.body.firstChild)).toBe('navigation');
    });
    it('HTML 语义标签映射', () => {
      document.body.innerHTML = '<button>x</button><a href="#">y</a><h1>t</h1>';
      expect(inferRole(document.body.children[0])).toBe('button');
      expect(inferRole(document.body.children[1])).toBe('link');
      expect(inferRole(document.body.children[2])).toBe('heading');
    });
    it('input 按 type 映射', () => {
      document.body.innerHTML = '<input type="email"><input type="checkbox">';
      expect(inferRole(document.body.children[0])).toBe('textbox');
      expect(inferRole(document.body.children[1])).toBe('checkbox');
    });
    it('无语义容器返回 null', () => {
      document.body.innerHTML = '<div></div><span></span>';
      expect(inferRole(document.body.children[0])).toBeNull();
      expect(inferRole(document.body.children[1])).toBeNull();
    });
    it('body 推断为 WebArea', () => {
      document.title = 'Test';
      expect(inferRole(document.body)).toBe('WebArea');
    });
    it('a 无 href 返回 null', () => {
      document.body.innerHTML = '<a>no link</a>';
      expect(inferRole(document.body.firstChild)).toBeNull();
    });
  });

  describe('computeName', () => {
    it('aria-label 优先', () => {
      document.body.innerHTML = '<button aria-label="提交">Submit</button>';
      expect(computeName(document.body.firstChild)).toBe('提交');
    });
    it('label for 关联表单字段', () => {
      document.body.innerHTML = '<label for="e">邮箱</label><input id="e" type="email">';
      expect(computeName(document.body.children[1])).toBe('邮箱');
    });
    it('包裹式 label', () => {
      document.body.innerHTML = '<label>搜索<input type="text"></label>';
      const input = document.querySelector('input');
      expect(computeName(input)).toBe('搜索');
    });
    it('textContent 兜底', () => {
      document.body.innerHTML = '<h1>用户登录</h1>';
      expect(computeName(document.body.firstChild)).toBe('用户登录');
    });
    it('placeholder 兜底', () => {
      document.body.innerHTML = '<input type="text" placeholder="请输入">';
      expect(computeName(document.body.firstChild)).toBe('请输入');
    });
    it('长文本截断到 200 字', () => {
      const long = 'a'.repeat(300);
      document.body.innerHTML = `<h1>${long}</h1>`;
      expect(computeName(document.body.firstChild).length).toBe(200);
    });
    it('无任何来源返回空串', () => {
      document.body.innerHTML = '<input type="text">';
      expect(computeName(document.body.firstChild)).toBe('');
    });
  });

  describe('isHidden', () => {
    it('hidden 属性', () => {
      document.body.innerHTML = '<div hidden></div>';
      expect(isHidden(document.body.firstChild)).toBe(true);
    });
    it('aria-hidden', () => {
      document.body.innerHTML = '<div aria-hidden="true"></div>';
      expect(isHidden(document.body.firstChild)).toBe(true);
    });
    it('display:none', () => {
      document.body.innerHTML = '<div style="display:none"></div>';
      expect(isHidden(document.body.firstChild)).toBe(true);
    });
    it('可见元素返回 false', () => {
      document.body.innerHTML = '<div>可见</div>';
      expect(isHidden(document.body.firstChild)).toBe(false);
    });
  });

  describe('isInteractive', () => {
    it('可交互 role 返回 true', () => {
      expect(isInteractive('button')).toBe(true);
      expect(isInteractive('link')).toBe(true);
      expect(isInteractive('textbox')).toBe(true);
    });
    it('非可交互 role 返回 false', () => {
      expect(isInteractive('heading')).toBe(false);
      expect(isInteractive('main')).toBe(false);
    });
  });
});
```

**Step 2: 运行测试确认失败**

Run: `npx vitest run test/content.test.js`
Expected: FAIL（模块不存在）。

**Step 3: 实现 ax-helpers.js**

创建 `chrome-extension/public/content/ax-helpers.js`：

```js
// AX 推断辅助函数（纯函数，可单测）
// 从 DOM/ARIA 推断无障碍树的 role / name / 可见性 / 可交互性

const INTERACTIVE_ROLES = new Set([
  'button', 'link', 'textbox', 'searchbox', 'checkbox', 'radio',
  'slider', 'spinbutton', 'switch', 'menuitem', 'menuitemcheckbox',
  'menuitemradio', 'tab', 'option', 'combobox', 'treeitem',
]);

const VALID_ROLES = new Set([
  'alert', 'application', 'article', 'banner', 'button', 'checkbox',
  'combobox', 'complementary', 'contentinfo', 'dialog', 'directory',
  'document', 'form', 'grid', 'gridcell', 'group', 'heading', 'img',
  'image', 'link', 'list', 'listbox', 'listitem', 'main', 'menu',
  'menubar', 'menuitem', 'menuitemcheckbox', 'menuitemradio',
  'navigation', 'none', 'note', 'option', 'presentation', 'progressbar',
  'radio', 'radiogroup', 'region', 'row', 'rowgroup', 'search',
  'searchbox', 'separator', 'slider', 'spinbutton', 'status', 'switch',
  'tab', 'tablist', 'tabpanel', 'textbox', 'timer', 'toolbar',
  'tooltip', 'treeitem', 'tree', 'treegrid',
]);

// HTML 标签 → ARIA role 映射（input 需按 type 二次判断）
const TAG_ROLE = {
  a: (el) => (el.hasAttribute('href') ? 'link' : null),
  button: () => 'button',
  nav: () => 'navigation',
  main: () => 'main',
  header: () => 'banner',
  footer: () => 'contentinfo',
  aside: () => 'complementary',
  section: () => 'region',
  form: () => 'form',
  search: () => 'search',
  h1: () => 'heading', h2: () => 'heading', h3: () => 'heading',
  h4: () => 'heading', h5: () => 'heading', h6: () => 'heading',
  ul: () => 'list', ol: () => 'list',
  li: () => 'listitem',
  img: () => 'image',
  select: () => 'combobox',
  textarea: () => 'textbox',
  table: () => 'table',
};

const INPUT_TYPE_ROLE = {
  email: 'textbox', text: 'textbox', password: 'textbox', search: 'searchbox',
  tel: 'textbox', url: 'textbox', number: 'spinbutton',
  checkbox: 'checkbox', radio: 'radio', range: 'slider',
};

export function inferRole(el) {
  // 优先级 0：body → WebArea
  if (el.tagName === 'BODY') return 'WebArea';

  // 优先级 1：显式 role（验证合法）
  const explicit = el.getAttribute('role');
  if (explicit && VALID_ROLES.has(explicit)) return explicit;

  // 优先级 2：标签映射
  const tag = el.tagName.toLowerCase();
  if (tag === 'input') {
    const type = (el.getAttribute('type') || 'text').toLowerCase();
    return INPUT_TYPE_ROLE[type] ?? null;
  }
  const mapper = TAG_ROLE[tag];
  return mapper ? mapper(el) : null;
}

export function computeName(el, maxLen = 200) {
  // 优先级 1：aria-labelledby
  const labelledby = el.getAttribute('aria-labelledby');
  if (labelledby) {
    const target = document.getElementById(labelledby);
    if (target) return truncate(target.textContent || '', maxLen);
  }
  // 优先级 2：aria-label
  const ariaLabel = el.getAttribute('aria-label');
  if (ariaLabel) return truncate(ariaLabel, maxLen);
  // 优先级 3：表单字段 label 关联
  if (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.tagName === 'SELECT') {
    const id = el.id;
    if (id) {
      const label = document.querySelector(`label[for="${id}"]`);
      if (label) return truncate(label.textContent || '', maxLen);
    }
    const wrapping = el.closest('label');
    if (wrapping) return truncate((wrapping.textContent || '').trim(), maxLen);
  }
  // 优先级 4：alt / title / placeholder / textContent
  const alt = el.getAttribute('alt');
  if (alt) return truncate(alt, maxLen);
  const title = el.getAttribute('title');
  if (title) return truncate(title, maxLen);
  const placeholder = el.getAttribute('placeholder');
  if (placeholder) return truncate(placeholder, maxLen);
  if (el.textContent) return truncate(el.textContent.trim(), maxLen);
  return '';
}

function truncate(s, maxLen) {
  return s.length > maxLen ? s.slice(0, maxLen) : s;
}

export function isHidden(el) {
  if (el.hasAttribute('hidden')) return true;
  if (el.getAttribute('aria-hidden') === 'true') return true;
  const style = window.getComputedStyle(el);
  if (style.display === 'none') return true;
  if (style.visibility === 'hidden') return true;
  return false;
}

export function isInteractive(role) {
  return INTERACTIVE_ROLES.has(role);
}
```

**Step 4: 运行测试确认通过**

Run: `npx vitest run test/content.test.js`
Expected: AX inference 块全部 PASS，旧用例不受影响。

**Step 5: Commit**

```bash
git add chrome-extension/public/content/ax-helpers.js chrome-extension/test/content.test.js
git commit -m "feat(content): AX 推断辅助函数——role/name/剪枝/可交互判定"
```

---

### Task 3: content.js — parsePage 单遍遍历 + action 路由 + 暴露

**Files:**
- Modify: `chrome-extension/public/content/content.js`（新增 parsePage、action 分支、暴露）
- Test: `chrome-extension/test/content.test.js`（新增 `describe('parsePage')` 块）

**注意：** `content.js` 头部注释说明"不使用 ES module export，因为 chrome.scripting.executeScript 不支持"。因此 `content.js` 通过全局 `__BU_AGENT__` 暴露。而 Task 2 的 `ax-helpers.js` 用 ES module 导出，**测试可直接 import**，但 content.js 不能 import 它。

**解决方案：** content.js 内联一份 parsePage（直接调用全局的 helper，或把 helpers 也挂到 `window.__BU_AGENT__`）。最干净的做法——把 ax-helpers.js 的逻辑也以非 module 形式注入。**实际做法：content.js 复制 helper 逻辑为内部函数（不依赖 import），ax-helpers.js 单独存在仅供测试**。为避免重复维护，采用更优方案：

**采用方案：** content.js 是 IIFE，在 IIFE 内定义 helper 函数（不 export），parsePage 调用它们。测试无法直接测 content.js 内部函数——**因此 Task 2 的 ax-helpers.js 是测试用的独立可测模块，content.js 内部复制相同逻辑**。这是 content script 不支持 module 的已知妥协。为减少重复，Task 2 的 ax-helpers.js 与 content.js 内部实现**保持代码一致**，并在两者头部注释互相引用。

**Step 1: 写失败测试（parsePage 整体行为）**

在 `test/content.test.js` 末尾追加（从 `__BU_AGENT__` 取 parsePage）：

```js
const { parsePage } = window.__BU_AGENT__;

describe('parsePage', () => {
  beforeEach(() => { document.body.innerHTML = ''; });

  it('输出嵌套 AX 树，顶层为 WebArea', () => {
    document.title = '测试页';
    document.body.innerHTML = '<button>登录</button>';
    const tree = parsePage();
    expect(tree.role).toBe('WebArea');
    expect(tree.name).toBe('测试页');
    expect(tree.children[0].role).toBe('button');
  });

  it('给可交互节点赋 agent-xx 并写入 DOM', () => {
    document.body.innerHTML = '<button>登录</button><h1>标题</h1>';
    const tree = parsePage();
    const btnNode = tree.children.find((c) => c.role === 'button');
    expect(btnNode.id).toMatch(/^agent-\d{2}$/);
    expect(document.querySelector('[backend-id="' + btnNode.id + '"]')).not.toBeNull();
  });

  it('纯文本/标题节点不赋 agent-xx', () => {
    document.body.innerHTML = '<h1>标题</h1><p>段落</p>';
    const tree = parsePage();
    const heading = tree.children.find((c) => c.role === 'heading');
    expect(heading.id).toBeUndefined();
    expect(document.querySelectorAll('[backend-id]').length).toBe(0);
  });

  it('隐藏节点被剪枝', () => {
    document.body.innerHTML = '<button>可见</button><div style="display:none"><button>隐藏</button></div>';
    const tree = parsePage();
    const labels = JSON.stringify(tree);
    expect(labels).toContain('可见');
    expect(labels).not.toContain('隐藏');
  });

  it('容器被剪但子节点上浮', () => {
    document.body.innerHTML = '<div><button>登录</button></div>';
    const tree = parsePage();
    // div 被剪，button 直接挂到 WebArea children
    expect(tree.children[0].role).toBe('button');
    expect(tree.children[0].name).toBe('登录');
  });

  it('accessible name 优先级：aria-label 胜过 textContent', () => {
    document.body.innerHTML = '<button aria-label="提交">Submit</button>';
    const tree = parsePage();
    expect(tree.children[0].name).toBe('提交');
  });

  it('重新调用先清理旧标记', () => {
    document.body.innerHTML = '<button>A</button>';
    parsePage();
    document.body.innerHTML = '<button>B</button><button>C</button>';
    parsePage();
    expect(document.querySelectorAll('[backend-id]').length).toBe(2);
  });

  it('body 为空返回空 children', () => {
    document.body.innerHTML = '';
    const tree = parsePage();
    expect(tree.role).toBe('WebArea');
    expect(tree.children).toEqual([]);
  });
});
```

**Step 2: 运行测试确认失败**

Run: `npx vitest run test/content.test.js`
Expected: FAIL（parsePage 未定义）。

**Step 3: 在 content.js 实现 parsePage**

在 `content.js` 的 IIFE 内（`tagElements` 之前）新增辅助函数（与 ax-helpers.js 逻辑一致）和 parsePage。在 action switch 加 `case 'parse_page'`。在 `window.__BU_AGENT__` 暴露 `parsePage`。

content.js IIFE 内新增（在 `let counter = 0;` 之后）：

```js
  // === AX 推断（与 ax-helpers.js 逻辑一致，content script 不支持 import，复制此份）===

  var AX_INTERACTIVE = {
    button:1, link:1, textbox:1, searchbox:1, checkbox:1, radio:1,
    slider:1, spinbutton:1, switch:1, menuitem:1, menuitemcheckbox:1,
    menuitemradio:1, tab:1, option:1, combobox:1, treeitem:1
  };
  var AX_VALID_ROLES = {
    alert:1, application:1, article:1, banner:1, button:1, checkbox:1,
    combobox:1, complementary:1, contentinfo:1, dialog:1, directory:1,
    document:1, form:1, grid:1, gridcell:1, group:1, heading:1, img:1,
    image:1, link:1, list:1, listbox:1, listitem:1, main:1, menu:1,
    menubar:1, menuitem:1, menuitemcheckbox:1, menuitemradio:1,
    navigation:1, none:1, note:1, option:1, presentation:1, progressbar:1,
    radio:1, radiogroup:1, region:1, row:1, rowgroup:1, search:1,
    searchbox:1, separator:1, slider:1, spinbutton:1, status:1, switch:1,
    tab:1, tablist:1, tabpanel:1, textbox:1, timer:1, toolbar:1, tooltip:1,
    treeitem:1, tree:1, treegrid:1, table:1
  };
  var AX_TAG_ROLE = {
    a: function(el){ return el.hasAttribute('href') ? 'link' : null; },
    button: function(){ return 'button'; },
    nav: function(){ return 'navigation'; },
    main: function(){ return 'main'; },
    header: function(){ return 'banner'; },
    footer: function(){ return 'contentinfo'; },
    aside: function(){ return 'complementary'; },
    section: function(){ return 'region'; },
    form: function(){ return 'form'; },
    search: function(){ return 'search'; },
    h1: function(){ return 'heading'; }, h2: function(){ return 'heading'; },
    h3: function(){ return 'heading'; }, h4: function(){ return 'heading'; },
    h5: function(){ return 'heading'; }, h6: function(){ return 'heading'; },
    ul: function(){ return 'list'; }, ol: function(){ return 'list'; },
    li: function(){ return 'listitem'; },
    img: function(){ return 'image'; },
    select: function(){ return 'combobox'; },
    textarea: function(){ return 'textbox'; },
    table: function(){ return 'table'; }
  };
  var AX_INPUT_TYPE_ROLE = {
    email:'textbox', text:'textbox', password:'textbox', search:'searchbox',
    tel:'textbox', url:'textbox', number:'spinbutton',
    checkbox:'checkbox', radio:'radio', range:'slider'
  };

  function axTruncate(s, maxLen) {
    maxLen = maxLen || 200;
    return s.length > maxLen ? s.slice(0, maxLen) : s;
  }
  function axInferRole(el) {
    if (el.tagName === 'BODY') return 'WebArea';
    var explicit = el.getAttribute('role');
    if (explicit && AX_VALID_ROLES[explicit]) return explicit;
    var tag = el.tagName.toLowerCase();
    if (tag === 'input') {
      var type = (el.getAttribute('type') || 'text').toLowerCase();
      return AX_INPUT_TYPE_ROLE[type] || null;
    }
    var mapper = AX_TAG_ROLE[tag];
    return mapper ? mapper(el) : null;
  }
  function axComputeName(el) {
    var labelledby = el.getAttribute('aria-labelledby');
    if (labelledby) {
      var target = document.getElementById(labelledby);
      if (target) return axTruncate((target.textContent || '').trim());
    }
    var ariaLabel = el.getAttribute('aria-label');
    if (ariaLabel) return axTruncate(ariaLabel);
    if (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.tagName === 'SELECT') {
      var id = el.id;
      if (id) {
        var label = document.querySelector('label[for="' + id + '"]');
        if (label) return axTruncate((label.textContent || '').trim());
      }
      var wrapping = el.closest('label');
      if (wrapping) return axTruncate((wrapping.textContent || '').trim());
    }
    var alt = el.getAttribute('alt');
    if (alt) return axTruncate(alt);
    var title = el.getAttribute('title');
    if (title) return axTruncate(title);
    var placeholder = el.getAttribute('placeholder');
    if (placeholder) return axTruncate(placeholder);
    if (el.textContent) return axTruncate(el.textContent.trim());
    return '';
  }
  function axIsHidden(el) {
    if (el.hasAttribute('hidden')) return true;
    if (el.getAttribute('aria-hidden') === 'true') return true;
    var style = window.getComputedStyle(el);
    if (style.display === 'none') return true;
    if (style.visibility === 'hidden') return true;
    return false;
  }
  function axIsInteractive(role) {
    return !!AX_INTERACTIVE[role];
  }

  function parsePage() {
    clearTags();
    counter = 0;
    var children = buildAxChildren(document.body);
    return {
      role: 'WebArea',
      name: document.title || '',
      children: children
    };
  }

  // 返回：node | array（上浮的子节点）| null
  function buildAxNode(el) {
    if (axIsHidden(el)) return null;
    var role = axInferRole(el);
    var name = axComputeName(el);

    var children = buildAxChildren(el);

    // 纯空容器：剪
    if (role === null && !name && children.length === 0) return null;
    // 容器无语义但有子节点：上浮子节点
    if (role === null && !name) return children;

    var node = { role: role };
    if (name) node.name = name;
    if (axIsInteractive(role)) {
      var id = 'agent-' + String(counter++).padStart(2, '0');
      el.setAttribute('backend-id', id);
      node.id = id;
    }
    if (children.length) node.children = children;
    return node;
  }

  function buildAxChildren(el) {
    var result = [];
    var kids = el.children;
    for (var i = 0; i < kids.length; i++) {
      var built = buildAxNode(kids[i]);
      if (!built) continue;
      if (Array.isArray(built)) {
        for (var j = 0; j < built.length; j++) result.push(built[j]);
      } else {
        result.push(built);
      }
    }
    return result;
  }
```

在 action switch（约 171 行附近）的 `case 'parse_dom':` 之前插入：

```js
              case 'parse_page':
                result = { success: true, data: { tree: parsePage() } };
                break;
```

在 `window.__BU_AGENT__` 对象（约 151 行）加入：

```js
    parsePage,
```

**Step 4: 运行测试确认通过**

Run: `npx vitest run test/content.test.js`
Expected: parsePage 块全部 PASS，旧用例不受影响。

**Step 5: Commit**

```bash
git add chrome-extension/public/content/content.js chrome-extension/test/content.test.js
git commit -m "feat(content): parsePage 单遍遍历产出 AX 树，新增 parse_page action"
```

---

### Task 4: background.ts + 类型 + UI 文案注册 parse_page

**Files:**
- Modify: `chrome-extension/src/entrypoints/background.ts:78`
- Modify: `chrome-extension/src/types/index.ts:25`
- Modify: `chrome-extension/src/components/EventCards.tsx:27,47`

**Step 1: background.ts action 路由**

把 `background.ts` 第 78 行：
```ts
case 'parse_dom': case 'get_element_info': case 'click': case 'input_text': case 'scroll': case 'scroll_element': case 'extract_content':
```
改为（加 `parse_page`）：
```ts
case 'parse_page': case 'parse_dom': case 'get_element_info': case 'click': case 'input_text': case 'scroll': case 'scroll_element': case 'extract_content':
```

**Step 2: 类型联合加 parse_page**

`src/types/index.ts` 第 25 行的 action 联合类型，在 `'parse_dom'` 前加 `'parse_page'`：
```ts
action: 'parse_page' | 'parse_dom' | 'get_element_info' | 'click' | 'input_text' | 'scroll' | 'enable_overlay' | 'disable_overlay'
```

**Step 3: EventCards 图标与文案**

`EventCards.tsx` 第 27 行图标映射加 `parse_page`（与 parse_dom 同图标或选一个"结构"类图标）。第 47 行文案映射加：
```ts
parse_page: '解析页面结构',
```

**Step 4: 类型检查**

Run（在 `chrome-extension/` 下）:
```bash
npx tsc --noEmit
```
Expected: 无类型错误。

**Step 5: Commit**

```bash
git add chrome-extension/src/entrypoints/background.ts chrome-extension/src/types/index.ts chrome-extension/src/components/EventCards.tsx
git commit -m "feat(ext): 注册 parse_page action 的路由、类型与 UI 文案"
```

---

### Task 5: config.yaml 新增 browser.dom_strategy

**Files:**
- Modify: `agent-core/config.yaml`

**Step 1: 加配置段**

在 `config.yaml` 末尾（`skills` 段之后）追加：
```yaml
browser:
  dom_strategy: ${DOM_STRATEGY:-ax}   # "ax"=新版 AX 树解析, "flat"=旧版扁平列表
```

**Step 2: Commit**

```bash
git add agent-core/config.yaml
git commit -m "feat(config): 新增 browser.dom_strategy 控制 DOM 解析策略"
```

---

### Task 6: ParsePage 工具（Python，TDD）

**Files:**
- Modify: `agent-core/browser/tools.py`（新增 `ParsePage` 类；删除 `ParseDom` 类；工厂改按 config 注册）
- Modify: `agent-core/tests/test_tools.py`

**Step 1: 写失败测试**

在 `tests/test_tools.py` 适当位置新增：

```python
def test_parse_page_default_strategy_is_ax(conn):
    """无 config 时默认 ax 策略，发 parse_page action。"""
    tool = _by_name(
        create_browser_tools(conn, vlm_model=None, viewport_info={}, dom_strategy="ax"),
        "parse_page",
    )
    conn.send_action = AsyncMock(return_value={
        "type": "result", "task_id": "t1", "status": "success",
        "data": {"tree": {"role": "WebArea", "name": "x", "children": []}},
    })
    result = await tool()
    sent = conn.send_action.call_args[0][0]
    assert sent["action"] == "parse_page"
    assert "WebArea" in _output_text(result)


def test_parse_page_flat_strategy_sends_parse_dom(conn):
    """flat 策略发 parse_dom action（旧）。"""
    tool = _by_name(
        create_browser_tools(conn, vlm_model=None, viewport_info={}, dom_strategy="flat"),
        "parse_page",
    )
    conn.send_action = AsyncMock(return_value={
        "type": "result", "task_id": "t1", "status": "success",
        "data": {"elements": [{"id": "agent-00", "tag": "button"}]},
    })
    result = await tool()
    sent = conn.send_action.call_args[0][0]
    assert sent["action"] == "parse_dom"
    assert "agent-00" in _output_text(result)
```

**Step 2: 运行测试确认失败**

Run（在 `agent-core/` 下）:
```bash
.venv/bin/python -m pytest tests/test_tools.py::test_parse_page_default_strategy_is_ax -v
```
Expected: FAIL（`create_browser_tools` 不接受 `dom_strategy` 参数，或 `parse_page` 不存在）。

**Step 3: 实现 ParsePage 并改造工厂**

在 `browser/tools.py`：

1. 删除 `ParseDom` 类（被取代）。

2. 新增 `ParsePage` 类（放在原 ParseDom 位置）：

```python
class ParsePage(_BrowserToolBase):
    """解析页面结构。

    按 dom_strategy 决定后端：
    - "ax"（默认）：发 parse_page，返回无障碍树语义结构。
    - "flat"：发 parse_dom，返回旧版扁平元素列表。
    对外 name 始终为 parse_page，切换对 LLM 透明。
    """

    name = "parse_page"
    description = (
        "解析当前页面结构，返回基于无障碍树的语义化嵌套 JSON。"
        "可交互元素（按钮/链接/输入框等）带 agent-xx 标识，"
        "可供 click_element/input_text 等工具引用。"
    )
    input_schema = {
        "type": "object",
        "properties": {},
        "required": [],
    }
    is_read_only = True
    is_concurrency_safe = True

    def __init__(self, conn: BrowserConnection, dom_strategy: str = "ax") -> None:
        super().__init__(conn)
        self._strategy = "ax" if dom_strategy == "ax" else "flat"

    async def __call__(self) -> ToolChunk:
        action = "parse_page" if self._strategy == "ax" else "parse_dom"
        result = await self._conn.send_action({"action": action})
        data = result.get("data", {})
        # ax 返回 {tree:{...}}，flat 返回 {elements:[...]}
        payload = data.get("tree", data.get("elements", []))
        return self._json(payload)
```

3. 改造 `create_browser_tools` 签名与工厂体：

```python
def create_browser_tools(
    conn: BrowserConnection,
    vlm_model,
    viewport_info: dict,
    dom_strategy: str = "ax",
) -> list[ToolBase]:
    """创建绑定到指定连接的所有浏览器工具实例。

    Args:
        conn: 浏览器连接实例。
        vlm_model: VLM 模型实例（供截图分析工具使用）。
        viewport_info: 视口信息字典（供 CDP 坐标换算使用）。
        dom_strategy: DOM 解析策略，"ax" 或 "flat"，决定 ParsePage 后端。

    Returns:
        组装好的 ToolBase 实例列表，可直接喂给 agentscope Toolkit。
    """
    return [
        # 页面结构解析（ax 或 flat，由 config 决定）
        ParsePage(conn, dom_strategy),
        # DOM 细节查询（只读）
        GetElementInfo(conn),
        ExtractContent(conn),
        # 操作执行（有副作用）
        ClickElement(conn),
        InputText(conn),
        ScrollPage(conn),
        ScrollElement(conn),
        Navigate(conn),
        GoBack(conn),
        Wait(conn),
        # 截图感知（只读，依赖 VLM）
        ScreenshotAnalyze(conn, vlm_model),
        # CDP 降级（有副作用，依赖 viewport_info）
        CdpClick(conn, viewport_info),
        # 元工具
        Done(),
    ]
```

**Step 4: 更新受影响的现有测试**

`tests/test_tools.py` 里所有调用 `create_browser_tools(conn, vlm_model=None, viewport_info={})` 的地方**无需改**（dom_strategy 有默认值）。但：

- 删除 `test_parse_dom`（工具已不存在）。
- `test_tool_registry_completeness`：工具数从 13 变为 **13**（ParseDom 替换为 ParsePage，总数不变），但 name 集合里 `"parse_dom"` 改为 `"parse_page"`：

```python
def test_tool_registry_completeness(conn):
    tools = create_browser_tools(conn, vlm_model=None, viewport_info={})
    names = [t.name for t in tools]
    assert len(names) == 13
    assert len(set(names)) == 13
    expected = {
        "parse_page", "get_element_info", "extract_content",
        "click_element", "input_text", "scroll_page", "scroll_element",
        "navigate", "go_back", "wait", "screenshot_analyze",
        "cdp_click", "done",
    }
    assert set(names) == expected
```

- `test_read_only_flags` 里 `"parse_dom"` 改为 `"parse_page"`（仍在只读集合）。

**Step 5: 运行全部 tools 测试确认通过**

Run:
```bash
.venv/bin/python -m pytest tests/test_tools.py -v
```
Expected: 全部 PASS（含新增 2 个 parse_page 测试）。

**Step 6: Commit**

```bash
git add agent-core/browser/tools.py agent-core/tests/test_tools.py
git commit -m "feat(tools): ParsePage 工具取代 ParseDom，按 config 策略切换后端"
```

---

### Task 7: create_toolkit 透传 dom_strategy

**Files:**
- Modify: `agent-core/agent/tools.py`

**Step 1: 透传配置**

`agent/tools.py` 的 `create_toolkit` 里，把 `create_browser_tools(conn, vlm_model, viewport_info)` 改为读取 config 并透传：

```python
    dom_strategy = config.get("browser", {}).get("dom_strategy", "ax")
    tool_objects = create_browser_tools(
        conn, vlm_model, viewport_info, dom_strategy=dom_strategy,
    )
```

**Step 2: 验证编译与现有测试**

Run:
```bash
.venv/bin/python -m py_compile agent/tools.py && .venv/bin/python -m pytest tests/test_tools.py -q
```
Expected: 编译通过，测试全 PASS。

**Step 3: Commit**

```bash
git add agent-core/agent/tools.py
git commit -m "feat(agent): create_toolkit 从 config 读取 dom_strategy 透传给工具"
```

---

### Task 8: 全量回归 + 集成验证

**Step 1: Python 全量测试**

Run（在 `agent-core/` 下）:
```bash
.venv/bin/python -m pytest
```
Expected: 仅 `test_parse_reflection`（预存失败，与本特性无关）失败，其余全 PASS。

**Step 2: content.js 全量测试**

Run（在 `chrome-extension/` 下）:
```bash
npx vitest run
```
Expected: 全 PASS。

**Step 3: TS 类型检查**

Run（在 `chrome-extension/` 下）:
```bash
npx tsc --noEmit
```
Expected: 无错误。

**Step 4: 手动集成验证（在真实浏览器）**

1. 用 `DOM_STRATEGY=ax`（默认）启动 agent-core，扩展加载新版 content.js。
2. 在一个登录页让 Agent 调用 `parse_page`，确认返回嵌套 AX 树 JSON。
3. 让 Agent 调用 `click_element(agent-00)`，确认能定位并点击 `parse_page` 标记的元素。
4. 改 `DOM_STRATEGY=flat` 重启，确认 `parse_page` 工具回退到扁平列表。

**Step 5: 最终 Commit（如有残留改动）**

```bash
git add -A && git commit -m "test: parse_page 特性全量回归通过" || echo "无需提交"
```

---

## 完成标准

- [ ] `parse_page` action 在 content.js 正确产出嵌套 AX 树
- [ ] content.js 全量测试 PASS（含新增 AX 推断与 parsePage 用例）
- [ ] background.ts / 类型 / UI 文案注册 parse_page
- [ ] `config.yaml` 新增 `browser.dom_strategy`，默认 `ax`
- [ ] `ParsePage` 工具按策略切换后端，对 LLM 透明（name 固定 parse_page）
- [ ] `ParseDom` 类删除，工具清单 name 集合更新
- [ ] Python 全量测试除预存 `test_parse_reflection` 外全 PASS
- [ ] 手动集成验证：click 能定位 parse_page 标记的元素
