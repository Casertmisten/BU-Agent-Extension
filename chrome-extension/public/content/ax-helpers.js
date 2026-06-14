// AX 推断辅助函数（纯函数，可单测）
// 从 DOM/ARIA 推断无障碍树的 role / name / 可见性 / 可交互性
//
// 注意：content.js 是 IIFE 不支持 import，会复制一份相同逻辑的内联实现。
// 本文件供测试使用，与 content.js 内联逻辑保持一致（见 Task 3）。

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
  'tooltip', 'treeitem', 'tree', 'treegrid', 'table',
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
