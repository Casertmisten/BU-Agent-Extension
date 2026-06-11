import { createWsClient } from '@/lib/ws-client'
import type { ContentMessage } from '@/types'

export default defineBackground(() => {
  chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true })

  const WS_URL = 'ws://localhost:8765'

  const wsClient = createWsClient(WS_URL, {
    heartbeatInterval: 30_000,
    reconnectBaseDelay: 1_000,
  })

  // Keep-alive
  chrome.alarms.create('keepAlive', { periodInMinutes: 1 })
  chrome.alarms.onAlarm.addListener((alarm) => {
    if (alarm.name === 'keepAlive' && !wsClient.isConnected()) {
      console.log('[BU-Agent] Alarm wakeup, reconnecting WS...')
      wsClient.connect()
    }
  })

  // WS 消息路由
  let isStreamingActive = false

  wsClient.onMessage((msg) => {
    const type = msg.type as string
    if (type === 'action') {
      handleAction(msg as Record<string, unknown> & { action: string; task_id: string })
    } else if (type === 'stream') {
      const streamContent = (msg as any).content as string
      // 流式开始时启用遮罩
      if (!isStreamingActive && streamContent !== '[DONE]') {
        isStreamingActive = true
        sendToContentScript({ action: 'enable_overlay' })
      }
      // 流式结束时关闭遮罩
      if (streamContent === '[DONE]') {
        isStreamingActive = false
        sendToContentScript({ action: 'disable_overlay' })
      }
      chrome.runtime.sendMessage(msg).catch(() => {})
    } else if (type === 'error') {
      // 出错时也关闭遮罩
      if (isStreamingActive) {
        isStreamingActive = false
        sendToContentScript({ action: 'disable_overlay' })
      }
      chrome.runtime.sendMessage(msg).catch(() => {})
    }
  })

  wsClient.onDisconnect(() => {
    console.log('[BU-Agent] WS disconnected, auto-reconnect enabled')
  })

  wsClient.connect()

  async function handleAction(msg: Record<string, unknown> & { action: string; task_id: string }) {
    const { action, task_id } = msg
    if (!action || !task_id) return

    try {
      let result
      switch (action) {
        case 'parse_dom': case 'get_element_info': case 'click': case 'input_text': case 'scroll':
          result = await executeInContentScript(msg); break
        case 'screenshot': result = await handleScreenshot(); break
        case 'navigate': result = await handleNavigate(msg.url as string); break
        case 'wait': result = await handleWait((msg.seconds as number) || 2); break
        case 'cdp_click': result = await handleCdpClick(msg.x as number, msg.y as number); break
        default: result = { status: 'error', error: `Unknown action: ${action}` }
      }
      wsClient.send({ type: 'result', task_id, status: (result as any).status || 'success', data: (result as any).data || {}, error: (result as any).error || '' })
    } catch (err) {
      wsClient.send({ type: 'result', task_id, status: 'error', error: (err as Error).message })
    }
  }

  async function executeInContentScript(msg: Record<string, unknown>) {
    const tab = await getActiveTab()
    if (!tab) return { status: 'error', error: 'No active tab' }
    await injectContentScript(tab.id!)
    return new Promise<Record<string, unknown>>((resolve) => {
      chrome.tabs.sendMessage(tab.id!, msg, (response) => {
        if (chrome.runtime.lastError) resolve({ status: 'error', error: chrome.runtime.lastError.message })
        else resolve(response || { status: 'error', error: 'No response from content script' })
      })
    })
  }

  async function injectContentScript(tabId: number) {
    try {
      await chrome.scripting.executeScript({ target: { tabId }, files: ['content/content.js'] })
    } catch (err) {
      console.warn('[BU-Agent] Content script inject:', (err as Error).message)
    }
  }

  async function handleScreenshot() {
    const tab = await getActiveTab()
    if (!tab) return { status: 'error', error: 'No active tab' }
    const dataUrl = await chrome.tabs.captureVisibleTab(tab.windowId, { format: 'png' })
    const base64 = dataUrl.replace(/^data:image\/png;base64,/, '')
    const dpr = await getPageDpr(tab.id!)
    return { status: 'success', data: { image: base64, viewport: { dpr, width: tab.width, height: tab.height } } }
  }

  async function getPageDpr(tabId: number) {
    try {
      const r = await chrome.scripting.executeScript({ target: { tabId }, func: () => window.devicePixelRatio })
      return r?.[0]?.result || 1.0
    } catch { return 1.0 }
  }

  async function handleNavigate(url: string) {
    const tab = await getActiveTab()
    if (!tab) return { status: 'error', error: 'No active tab' }
    return new Promise<Record<string, unknown>>((resolve) => {
      const listener = (id: number, info: chrome.tabs.TabChangeInfo) => {
        if (id === tab.id && info.status === 'complete') {
          chrome.tabs.onUpdated.removeListener(listener)
          injectContentScript(tab.id!).then(() => resolve({ status: 'success', data: { url: info.url || url } }))
        }
      }
      chrome.tabs.onUpdated.addListener(listener)
      chrome.tabs.update(tab.id!, { url })
      setTimeout(() => { chrome.tabs.onUpdated.removeListener(listener); resolve({ status: 'error', error: 'Navigation timeout' }) }, 15_000)
    })
  }

  async function handleWait(seconds: number) {
    await new Promise((r) => setTimeout(r, seconds * 1000))
    return { status: 'success', data: {} }
  }

  async function handleCdpClick(x: number, y: number) {
    const tab = await getActiveTab()
    if (!tab) return { status: 'error', error: 'No active tab' }
    try {
      await chrome.debugger.attach({ tabId: tab.id! }, '1.3')
      await chrome.debugger.sendCommand({ tabId: tab.id! }, 'Input.dispatchMouseEvent', { type: 'mousePressed', x, y, button: 'left', clickCount: 1 })
      await chrome.debugger.sendCommand({ tabId: tab.id! }, 'Input.dispatchMouseEvent', { type: 'mouseReleased', x, y, button: 'left', clickCount: 1 })
      await chrome.debugger.detach({ tabId: tab.id! })
      return { status: 'success', data: {} }
    } catch (err) {
      try { await chrome.debugger.detach({ tabId: tab.id! }) } catch {}
      return { status: 'error', error: `CDP click failed: ${(err as Error).message}` }
    }
  }

  // SidePanel 通信
  chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    if (message.type === 'user_message') {
      wsClient.send({ type: 'user_message', content: message.content })
      sendResponse({ received: true })
    }
    if (message.type === 'get_status') {
      sendResponse({ connected: wsClient.isConnected() })
    }
    return false
  })

  async function sendToContentScript(msg: Record<string, unknown>) {
    const tab = await getActiveTab()
    if (!tab) return
    await injectContentScript(tab.id!)
    chrome.tabs.sendMessage(tab.id!, msg).catch(() => {})
  }

  async function getActiveTab() {
    const tabs = await chrome.tabs.query({ active: true, currentWindow: true })
    return tabs?.[0] || null
  }
})
