let counter = 0;

export function tagElements() {
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

export function clearTags() {
  document.querySelectorAll('[backend-id]').forEach((el) => {
    el.removeAttribute('backend-id');
  });
}

export function get_element_info(targetId) {
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

export function clickElement(targetId) {
  const el = document.querySelector(`[backend-id="${targetId}"]`);
  if (!el) return { success: false, error: `Element ${targetId} not found` };
  el.click();
  return { success: true };
}

export function inputText(targetId, text, clearFirst = true) {
  const el = document.querySelector(`[backend-id="${targetId}"]`);
  if (!el) return { success: false, error: `Element ${targetId} not found` };

  el.focus();
  if (clearFirst) el.value = '';
  el.value += text;
  el.dispatchEvent(new Event('input', { bubbles: true }));
  el.dispatchEvent(new Event('change', { bubbles: true }));
  return { success: true };
}

export function scrollPage(direction, pixels) {
  const x = direction === 'left' ? -pixels : direction === 'right' ? pixels : 0;
  const y = direction === 'up' ? -pixels : direction === 'down' ? pixels : 0;
  window.scrollBy(x, y);
  return { success: true };
}

// --- Overlay ---

let overlay = null;

export function enableOverlay() {
  if (overlay) return;
  overlay = document.createElement('div');
  overlay.id = '__agent_overlay__';
  overlay.style.cssText = `
    position: fixed; top: 0; left: 0;
    width: 100vw; height: 100vh;
    z-index: 999999;
    background: rgba(0, 0, 0, 0.15);
    pointer-events: auto;
  `;
  document.body.appendChild(overlay);
}

export function disableOverlay() {
  if (overlay) {
    overlay.remove();
    overlay = null;
  }
}

// --- Production message listener (disabled in tests) ---
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
