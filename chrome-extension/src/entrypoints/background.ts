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
  // 缓存后端推送的技能清单：skills_list 仅在连接时推送一次，sidepanel 可能晚于
  // 推送打开，需缓存以便 sidepanel 挂载时通过 get_skills 拉取（仿 get_status 模式）。
  let cachedSkills: unknown[] = []

  wsClient.onMessage((msg) => {
    const type = msg.type as string
    if (type === 'action') {
      handleAction(msg as Record<string, unknown> & { action: string; task_id: string })
    } else if (type === 'stream') {
      chrome.runtime.sendMessage(msg).catch(() => {})
    } else if (type === 'event') {
      // activity_status 事件驱动遮罩：thinking/executing 显示，done/error 隐藏。
      // 不依赖 stream 文本，避免模型直接工具调用（无文本输出）时遮罩不显示。
      const evt = (msg as any).event
      if (evt?.type === 'activity_status') {
        const status = evt.data?.status
        if ((status === 'thinking' || status === 'executing') && !isStreamingActive) {
          isStreamingActive = true
          sendToContentScript({ action: 'enable_overlay' })
        } else if ((status === 'done' || status === 'error') && isStreamingActive) {
          isStreamingActive = false
          sendToContentScript({ action: 'disable_overlay' })
        }
      }
      // 转发 agent 事件（step/reflection/activity_status）到 sidepanel
      chrome.runtime.sendMessage(msg).catch(() => {})
    } else if (type === 'error') {
      // 出错时也关闭遮罩
      if (isStreamingActive) {
        isStreamingActive = false
        sendToContentScript({ action: 'disable_overlay' })
      }
      chrome.runtime.sendMessage(msg).catch(() => {})
    } else if (type === 'skills_list') {
      // 缓存并转发后端推送的技能清单到 sidepanel
      cachedSkills = (msg as any).skills ?? []
      chrome.runtime.sendMessage(msg).catch(() => {})
    } else if (type.startsWith('record_')) {
      // 转发所有 record_* 消息到 SidePanel
      chrome.runtime.sendMessage(msg).catch(() => {})
    }
  })

  wsClient.onDisconnect(() => {
    console.log('[BU-Agent] WS disconnected, auto-reconnect enabled')
  })

  wsClient.connect()

  // ====== 录制功能 ======
  // 录制会话：trace_id → {tabId, buffer, seq, label}
  let activeRecordSession: {
    trace_id: string
    tabId: number
    buffer: any[]
    seq: number
    label: string
    flushTimer: ReturnType<typeof setInterval> | null
  } | null = null

  const RECORD_BATCH_SIZE = 500
  const RECORD_FLUSH_INTERVAL_MS = 2000  // 定时 flush，避免低频录制时事件积压

  /** 注入录制 content script 到目标 tab */
  async function injectRecorder(tabId: number) {
    try {
      await chrome.scripting.executeScript({
        target: { tabId },
        files: ['recorder.content.js'],
      })
    } catch (err) {
      console.warn('[BU-Agent] Recorder inject:', (err as Error).message)
    }
  }

  /** 把缓冲区事件批量发到后端 */
  function flushRecordBuffer() {
    if (!activeRecordSession || !wsClient.isConnected()) return
    const session = activeRecordSession
    if (session.buffer.length === 0) return

    const events = session.buffer.splice(0, RECORD_BATCH_SIZE)
    session.seq += 1
    wsClient.send({
      type: 'record_event',
      trace_id: session.trace_id,
      events,
      seq: session.seq,
    })
  }

  /** 启动录制：注入 content + 发 record_start + 启动定时 flush */
  async function startRecording(tabId: number, label: string): Promise<string | null> {
    if (activeRecordSession) {
      console.warn('[BU-Agent] 已有录制进行中')
      return null
    }
    const trace_id = crypto.randomUUID().replace(/-/g, '').slice(0, 12)
    activeRecordSession = {
      trace_id,
      tabId,
      buffer: [],
      seq: 0,
      label,
      flushTimer: setInterval(flushRecordBuffer, RECORD_FLUSH_INTERVAL_MS),
    }

    await injectRecorder(tabId)

    // 注入后给 content 发 start 指令
    chrome.tabs.sendMessage(tabId, {
      type: 'record_start_content',
      trace_id,
      tab_id: tabId,
    }).catch(() => {})

    wsClient.send({ type: 'record_start', tab_id: tabId, label })
    chrome.action.setBadgeText({ text: '●' })
    chrome.action.setBadgeBackgroundColor({ color: '#ef4444' })
    return trace_id
  }

  /** 停止录制：flush 剩余 + 发 record_stop + 卸载 content */
  async function stopRecording(finalLabel?: string): Promise<void> {
    if (!activeRecordSession) return
    const session = activeRecordSession

    // 通知 content 停止（content 会 flush mutation summary）
    chrome.tabs.sendMessage(session.tabId, { type: 'record_stop_content' }).catch(() => {})

    // 等待 content flush 完成（短延迟确保 mutation 事件到达）
    await new Promise((r) => setTimeout(r, 200))

    // 最后 flush 一次
    flushRecordBuffer()
    if (session.flushTimer) {
      clearInterval(session.flushTimer)
    }

    wsClient.send({
      type: 'record_stop',
      trace_id: session.trace_id,
      label: finalLabel || session.label,
    })

    chrome.action.setBadgeText({ text: '' })
    activeRecordSession = null
  }

  async function handleAction(msg: Record<string, unknown> & { action: string; task_id: string }) {
    const { action, task_id } = msg
    if (!action || !task_id) return

    try {
      let result
      switch (action) {
        case 'parse_page': case 'parse_dom': case 'get_element_info': case 'click': case 'input_text': case 'scroll': case 'scroll_element': case 'extract_content':
          result = await executeInContentScript(msg); break
        case 'screenshot': result = await handleScreenshot(); break
        case 'navigate': result = await handleNavigate(msg.url as string); break
        case 'wait': result = await handleWait((msg.seconds as number) || 2); break
        case 'cdp_click': result = await handleCdpClick(msg.x as number, msg.y as number); break
        case 'go_back': result = await handleGoBack(); break
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
    // 等比缩放到不超过 1920×1080 并转 JPEG(0.85)，减小回传体积供后端 VLM 识别
    const base64 = await compressImage(dataUrl, 1920, 1080)
    const dpr = await getPageDpr(tab.id!)
    return { status: 'success', data: { image: base64, viewport: { dpr, width: tab.width, height: tab.height } } }
  }

  /** 将 dataUrl 图片等比缩放到不超过 maxW×maxH（不放大），输出 JPEG 纯 base64。 */
  async function compressImage(dataUrl: string, maxW: number, maxH: number): Promise<string> {
    const blob = await (await fetch(dataUrl)).blob()
    const bitmap = await createImageBitmap(blob)
    const scale = Math.min(maxW / bitmap.width, maxH / bitmap.height, 1)
    const w = Math.round(bitmap.width * scale)
    const h = Math.round(bitmap.height * scale)
    const canvas = new OffscreenCanvas(w, h)
    const ctx = canvas.getContext('2d')
    if (!ctx) throw new Error('OffscreenCanvas 2D context unavailable')
    ctx.drawImage(bitmap, 0, 0, w, h)
    bitmap.close()
    const outBlob = await canvas.convertToBlob({ type: 'image/jpeg', quality: 0.85 })
    return blobToBase64(outBlob)
  }

  /** 将 Blob 编码为纯 base64 字符串（service worker 无 FileReader，手动编码）。 */
  async function blobToBase64(blob: Blob): Promise<string> {
    const bytes = new Uint8Array(await blob.arrayBuffer())
    let binary = ''
    const chunk = 0x8000
    for (let i = 0; i < bytes.length; i += chunk) {
      binary += String.fromCharCode(...bytes.subarray(i, i + chunk))
    }
    return btoa(binary)
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
      const listener = (id: number, info: any) => {
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

  async function handleGoBack() {
    const tab = await getActiveTab()
    if (!tab) return { status: 'error', error: 'No active tab' }
    return new Promise<Record<string, unknown>>((resolve) => {
      const listener = (id: number, info: any) => {
        if (id === tab.id && info.status === 'complete') {
          chrome.tabs.onUpdated.removeListener(listener)
          resolve({ status: 'success', data: {} })
        }
      }
      chrome.tabs.onUpdated.addListener(listener)
      chrome.tabs.goBack(tab.id!)
      setTimeout(() => { chrome.tabs.onUpdated.removeListener(listener); resolve({ status: 'error', error: 'Go back timeout' }) }, 10_000)
    })
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
    if (message.type === 'get_skills') {
      // sidepanel 挂载时拉取缓存的技能清单（见 cachedSkills 注释）
      sendResponse({ skills: cachedSkills })
    }
    if (message.type === 'stop') {
      // 转发停止指令给后端 agent
      wsClient.send({ type: 'stop' })
      if (isStreamingActive) {
        isStreamingActive = false
        sendToContentScript({ action: 'disable_overlay' })
      }
      sendResponse({ stopped: true })
    }
    if (message.type === 'new_session') {
      // 转发新建会话指令给后端，并乐观关闭遮罩
      wsClient.send({ type: 'new_session' })
      if (isStreamingActive) {
        isStreamingActive = false
        sendToContentScript({ action: 'disable_overlay' })
      }
      sendResponse({ received: true })
    }
    if (message.type === 'record_start') {
      getActiveTab().then((tab) => {
        if (tab?.id) {
          startRecording(tab.id, message.label || '').then((trace_id) => {
            sendResponse({ trace_id })
          })
        } else {
          sendResponse({ trace_id: null })
        }
      })
      return true  // 异步响应
    }
    if (message.type === 'record_stop') {
      stopRecording(message.label).then(() => sendResponse({ stopped: true }))
      return true
    }
    if (message.type === 'record_redistill') {
      wsClient.send({ type: 'record_redistill', trace_id: message.trace_id })
      sendResponse({ received: true })
    }
    if (message.type === 'record_event_content') {
      // content script 发来的单条事件 → 聚合到 buffer
      if (activeRecordSession && message.event) {
        activeRecordSession.buffer.push(message.event)
        // 满 batch 立即 flush
        if (activeRecordSession.buffer.length >= RECORD_BATCH_SIZE) {
          flushRecordBuffer()
        }
      }
    }
    if (message.type === 'get_recorder_state') {
      sendResponse({
        active: activeRecordSession !== null,
        trace_id: activeRecordSession?.trace_id ?? null,
        eventCount: activeRecordSession?.buffer.length ?? 0,
      })
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
