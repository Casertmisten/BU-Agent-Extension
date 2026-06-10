import { createWsClient } from './libs/ws-client.js';

const WS_URL = 'ws://localhost:8765';

const wsClient = createWsClient(WS_URL, {
  heartbeatInterval: 30000,
  reconnectBaseDelay: 1000,
});

// --- Keep-alive via chrome.alarms ---
chrome.alarms.create('keepAlive', { periodInMinutes: 1 });
chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === 'keepAlive') {
    if (!wsClient.isConnected()) {
      console.log('[BU-Agent] Alarm wakeup, reconnecting WS...');
      wsClient.connect();
    }
  }
});

// --- Route messages from WebSocket ---
wsClient.onMessage((msg) => {
  if (msg.type === 'action') {
    handleAction(msg);
  } else if (msg.type === 'stream') {
    chrome.runtime.sendMessage(msg).catch(() => {});
  }
});

wsClient.onDisconnect(() => {
  console.log('[BU-Agent] WS disconnected, auto-reconnect enabled');
});

wsClient.connect();

// --- Action router ---
async function handleAction(msg) {
  const { action, task_id } = msg;
  if (!action || !task_id) return;

  try {
    let result;

    switch (action) {
      case 'parse_dom':
      case 'get_element_info':
      case 'click':
      case 'input_text':
      case 'scroll':
        result = await executeInContentScript(msg);
        break;

      case 'screenshot':
        result = await handleScreenshot();
        break;
      case 'navigate':
        result = await handleNavigate(msg.url);
        break;
      case 'wait':
        result = await handleWait(msg.seconds || 2);
        break;
      case 'cdp_click':
        result = await handleCdpClick(msg.x, msg.y);
        break;

      default:
        result = { status: 'error', error: `Unknown action: ${action}` };
    }

    wsClient.send({
      type: 'result',
      task_id,
      status: result.status || 'success',
      data: result.data || {},
      error: result.error || '',
    });
  } catch (err) {
    wsClient.send({
      type: 'result',
      task_id,
      status: 'error',
      error: err.message,
    });
  }
}

// --- Content Script execution ---
async function executeInContentScript(msg) {
  const tab = await getActiveTab();
  if (!tab) return { status: 'error', error: 'No active tab' };

  await injectContentScript(tab.id);

  return new Promise((resolve) => {
    chrome.tabs.sendMessage(tab.id, msg, (response) => {
      if (chrome.runtime.lastError) {
        resolve({ status: 'error', error: chrome.runtime.lastError.message });
      } else {
        resolve(response || { status: 'error', error: 'No response from content script' });
      }
    });
  });
}

async function injectContentScript(tabId) {
  try {
    await chrome.scripting.executeScript({
      target: { tabId },
      files: ['content/content.js'],
    });
  } catch (err) {
    console.warn('[BU-Agent] Content script inject (may already exist):', err.message);
  }
}

// --- Screenshot ---
async function handleScreenshot() {
  const tab = await getActiveTab();
  if (!tab) return { status: 'error', error: 'No active tab' };

  const dataUrl = await chrome.tabs.captureVisibleTab(tab.windowId, { format: 'png' });
  const base64 = dataUrl.replace(/^data:image\/png;base64,/, '');

  const dpr = await getPageDpr(tab.id);
  return {
    status: 'success',
    data: { image: base64, viewport: { dpr, width: tab.width, height: tab.height } },
  };
}

async function getPageDpr(tabId) {
  try {
    const results = await chrome.scripting.executeScript({
      target: { tabId },
      func: () => window.devicePixelRatio,
    });
    return results?.[0]?.result || 1.0;
  } catch {
    return 1.0;
  }
}

// --- Navigate ---
async function handleNavigate(url) {
  const tab = await getActiveTab();
  if (!tab) return { status: 'error', error: 'No active tab' };

  return new Promise((resolve) => {
    const listener = (updatedTabId, changeInfo) => {
      if (updatedTabId === tab.id && changeInfo.status === 'complete') {
        chrome.tabs.onUpdated.removeListener(listener);
        injectContentScript(tab.id).then(() => {
          resolve({ status: 'success', data: { url: changeInfo.url || url } });
        });
      }
    };
    chrome.tabs.onUpdated.addListener(listener);
    chrome.tabs.update(tab.id, { url });

    setTimeout(() => {
      chrome.tabs.onUpdated.removeListener(listener);
      resolve({ status: 'error', error: 'Navigation timeout (15s)' });
    }, 15000);
  });
}

// --- Wait ---
async function handleWait(seconds) {
  await new Promise((resolve) => setTimeout(resolve, seconds * 1000));
  return { status: 'success', data: {} };
}

// --- CDP click ---
async function handleCdpClick(x, y) {
  const tab = await getActiveTab();
  if (!tab) return { status: 'error', error: 'No active tab' };

  try {
    await chrome.debugger.attach({ tabId: tab.id }, '1.3');
    await chrome.debugger.sendCommand({ tabId: tab.id }, 'Input.dispatchMouseEvent', {
      type: 'mousePressed', x, y, button: 'left', clickCount: 1,
    });
    await chrome.debugger.sendCommand({ tabId: tab.id }, 'Input.dispatchMouseEvent', {
      type: 'mouseReleased', x, y, button: 'left', clickCount: 1,
    });
    await chrome.debugger.detach({ tabId: tab.id });
    return { status: 'success', data: {} };
  } catch (err) {
    try { await chrome.debugger.detach({ tabId: tab.id }); } catch {}
    return { status: 'error', error: `CDP click failed: ${err.message}` };
  }
}

// --- Mode change ---
async function handleModeChange(mode) {
  const tab = await getActiveTab();
  if (!tab) return { status: 'error', error: 'No active tab' };

  await injectContentScript(tab.id);
  return new Promise((resolve) => {
    chrome.tabs.sendMessage(tab.id, {
      action: mode === 'ai' ? 'enable_overlay' : 'disable_overlay',
    }, (response) => {
      if (chrome.runtime.lastError) {
        resolve({ status: 'error', error: chrome.runtime.lastError.message });
      } else {
        resolve({ status: 'success', data: { mode } });
      }
    });
  });
}

// --- SidePanel communication ---
chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message.type === 'user_message') {
    wsClient.send({ type: 'user_message', content: message.content });
    sendResponse({ received: true });
  }

  if (message.type === 'mode_change') {
    handleModeChange(message.mode).then((result) => {
      wsClient.send({ type: 'mode_change', mode: message.mode });
      sendResponse(result);
    });
    return true;
  }

  if (message.type === 'get_status') {
    sendResponse({ connected: wsClient.isConnected() });
  }

  return false;
});

// --- Helper ---
async function getActiveTab() {
  const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
  return tabs?.[0] || null;
}
