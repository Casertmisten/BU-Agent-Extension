// content.js — Browser Use Agent Content Script
// 注入到页面中，处理 DOM 操作和元素打标。
// 不使用 ES module export，因为 chrome.scripting.executeScript 不支持。
// 函数通过全局对象 __BU_AGENT__ 暴露，供测试和外部使用。

(function () {
  'use strict';

  let counter = 0;

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

    var children = buildAxChildren(el);

    // role=null 的节点（div/span 等无语义容器）一律上浮子节点：
    // 其 textContent/name 必然来自子节点，保留会造成冗余层级。
    if (role === null) {
      if (children.length === 0) return null;
      return children;
    }

    var name = axComputeName(el);
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

  function tagElements() {
    clearTags();
    counter = 0;

    const interactable = document.querySelectorAll(
      'a, button, input, select, textarea, [role="button"], [onclick]'
    );
    const elements = [];

    interactable.forEach((el) => {
      const id = String(counter++).padStart(2, '0');
      el.setAttribute('backend-id', `agent-${id}`);
      elements.push({
        id: `agent-${id}`,
        tag: el.tagName.toLowerCase(),
        text: (el.textContent || '').trim().slice(0, 50),
        type: el.tagName === 'INPUT' ? (el.type || '') : '',
        placeholder: el.placeholder || '',
      });
    });

    return elements;
  }

  function clearTags() {
    document.querySelectorAll('[backend-id]').forEach((el) => {
      el.removeAttribute('backend-id');
    });
  }

  function get_element_info(targetId) {
    const el = document.querySelector(`[backend-id="${targetId}"]`);
    if (!el) return null;

    const rect = el.getBoundingClientRect();
    const style = window.getComputedStyle(el);
    const visible = style.display !== 'none' && style.visibility !== 'hidden' && !el.hidden;
    return {
      tag: el.tagName.toLowerCase(),
      type: el.tagName === 'INPUT' ? (el.type || '') : '',
      text: (el.textContent || '').trim(),
      placeholder: el.placeholder || '',
      value: el.value || '',
      href: el.href || '',
      visible,
      rect: { x: rect.x, y: rect.y, width: rect.width, height: rect.height },
      attributes: Object.fromEntries(
        Array.from(el.attributes)
          .filter((attr) => attr.name !== 'backend-id')
          .map((attr) => [attr.name, attr.value])
      ),
    };
  }

  function clickElement(targetId) {
    const el = document.querySelector(`[backend-id="${targetId}"]`);
    if (!el) return { success: false, error: `Element ${targetId} not found` };
    el.click();
    return { success: true };
  }

  function inputText(targetId, text, clearFirst = true) {
    const el = document.querySelector(`[backend-id="${targetId}"]`);
    if (!el) return { success: false, error: `Element ${targetId} not found` };

    el.focus();
    if (clearFirst) el.value = '';
    el.value += text;
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
    return { success: true };
  }

  function scrollPage(direction, pixels) {
    const x = direction === 'left' ? -pixels : direction === 'right' ? pixels : 0;
    const y = direction === 'up' ? -pixels : direction === 'down' ? pixels : 0;
    window.scrollBy(x, y);
    return { success: true };
  }


  function scrollElement(targetId, direction, pixels) {
    var el = document.querySelector('[backend-id="' + targetId + '"]');
    if (!el) return { success: false, error: 'Element ' + targetId + ' not found' };
    var x = direction === 'left' ? -pixels : direction === 'right' ? pixels : 0;
    var y = direction === 'up' ? -pixels : direction === 'down' ? pixels : 0;
    el.scrollBy(x, y);
    return { success: true };
  }

  function extractContent(targetId) {
    if (targetId) {
      var el = document.querySelector('[backend-id="' + targetId + '"]');
      if (!el) return { success: false, error: 'Element ' + targetId + ' not found' };
      return { success: true, data: { text: (el.textContent || '').trim(), html: el.innerHTML } };
    }
    return { success: true, data: { text: (document.body.textContent || '').trim().slice(0, 5000), title: document.title, url: window.location.href } };
  }

  // --- Overlay ---

  let overlay = null;

  function enableOverlay() {
    if (overlay) return;
    // 防止重复注入 content script 导致 overlay 变量丢失
    var existing = document.getElementById('__agent_overlay__');
    if (existing) { overlay = existing; return; }
    // 注入呼吸动画样式
    if (!document.getElementById('__agent_overlay_style__')) {
      var s = document.createElement('style');
      s.id = '__agent_overlay_style__';
      s.textContent = '@keyframes __agent_breath__ {' +
'0%, 100% { box-shadow: inset 0 0 30px rgba(99,102,241,0.25), 0 0 15px rgba(168,85,247,0.15); }' +
'25% { box-shadow: inset 0 0 45px rgba(59,130,246,0.35), 0 0 20px rgba(99,102,241,0.2); }' +
'50% { box-shadow: inset 0 0 60px rgba(168,85,247,0.45), 0 0 30px rgba(236,72,153,0.3); }' +
'75% { box-shadow: inset 0 0 45px rgba(236,72,153,0.35), 0 0 20px rgba(249,115,22,0.2); }' +
 '}';
      document.head.appendChild(s);
    }
    overlay = document.createElement('div');
    overlay.id = '__agent_overlay__';
    overlay.style.cssText =
      'position:fixed;top:0;left:0;' +
      'width:100vw;height:100vh;' +
      'z-index:999999;' +
      'background:transparent;' +
      'pointer-events:auto;' +
      'animation:__agent_breath__ 3s ease-in-out infinite;';
    document.body.appendChild(overlay);
  }

  function disableOverlay() {
    if (overlay) {
      overlay.remove();
      overlay = null;
    }
  }

  // --- 暴露给测试和外部使用 ---
  window.__BU_AGENT__ = {
    tagElements,
    parsePage,
    clearTags,
    get_element_info,
    clickElement,
    inputText,
    scrollPage,
    enableOverlay,
    disableOverlay,
  };

  // --- 消息监听 ---
  if (typeof chrome !== 'undefined' && chrome.runtime && !globalThis.__TEST__) {
    chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
      const action = message.action;
      if (!action) return false;

      try {
        let result;
        switch (action) {
          case 'parse_page':
            result = { success: true, data: { tree: parsePage() } };
            break;
          case 'parse_dom':
            result = { success: true, data: { elements: tagElements() } };
            break;
          case 'get_element_info':
            result = { success: true, data: get_element_info(message.target_id) };
            break;
          case 'click':
            result = clickElement(message.target_id);
            break;
          case 'input_text':
            result = inputText(message.target_id, message.text, message.clear_first);
            break;
          case 'scroll':
            result = scrollPage(message.direction, message.pixels);
            break;
          case 'scroll_element':
            result = scrollElement(message.target_id, message.direction, message.pixels);
            break;
          case 'extract_content':
            result = extractContent(message.target_id);
            break;
          case 'enable_overlay':
            enableOverlay();
            result = { success: true };
            break;
          case 'disable_overlay':
            disableOverlay();
            result = { success: true };
            break;
          default:
            result = { success: false, error: `Unknown action: ${action}` };
        }
        sendResponse(result);
      } catch (err) {
        sendResponse({ success: false, error: err.message });
      }
      return false;
    });

    chrome.runtime.sendMessage({
      type: 'page_ready',
      url: window.location.href,
      viewport: {
        dpr: window.devicePixelRatio,
        width: window.innerWidth,
        height: window.innerHeight,
      },
    });
  }
})();
