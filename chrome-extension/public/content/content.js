// content.js — Browser Use Agent Content Script
// 注入到页面中，处理 DOM 操作和元素打标。
// 不使用 ES module export，因为 chrome.scripting.executeScript 不支持。
// 函数通过全局对象 __BU_AGENT__ 暴露，供测试和外部使用。

(function () {
  'use strict';

  let counter = 0;

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
