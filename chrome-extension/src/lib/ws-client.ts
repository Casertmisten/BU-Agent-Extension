/** WebSocket 客户端（从 ws-client.js 迁移，加类型注解） */

export interface WsClientOptions {
  heartbeatInterval?: number
  reconnectBaseDelay?: number
}

export interface WsClient {
  connect: () => Promise<void>
  send: (data: unknown) => void
  destroy: () => void
  onMessage: (cb: (msg: Record<string, unknown>) => void) => void
  onDisconnect: (cb: () => void) => void
  isConnected: () => boolean
}

export function createWsClient(url: string, options: WsClientOptions = {}): WsClient {
  const heartbeatInterval = options.heartbeatInterval ?? 30_000
  const reconnectBaseDelay = options.reconnectBaseDelay ?? 1_000

  let ws: WebSocket | null = null
  let connected = false
  let heartbeatTimer: ReturnType<typeof setInterval> | null = null
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null
  let reconnectAttempts = 0
  let messageCallback: ((msg: Record<string, unknown>) => void) | null = null
  let disconnectCallback: (() => void) | null = null
  let destroyed = false

  function startHeartbeat() {
    stopHeartbeat()
    heartbeatTimer = setInterval(() => {
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'heartbeat', ts: Date.now() / 1000 }))
      }
    }, heartbeatInterval)
  }

  function stopHeartbeat() {
    if (heartbeatTimer) {
      clearInterval(heartbeatTimer)
      heartbeatTimer = null
    }
  }

  function scheduleReconnect() {
    if (destroyed) return
    const delay = Math.min(reconnectBaseDelay * Math.pow(2, reconnectAttempts), 30_000)
    reconnectAttempts++
    reconnectTimer = setTimeout(() => connect(), delay)
  }

  function connect(): Promise<void> {
    return new Promise((resolve) => {
      ws = new WebSocket(url)

      ws.onopen = () => {
        connected = true
        reconnectAttempts = 0
        startHeartbeat()
        resolve()
      }

      ws.onmessage = (event) => {
        try {
          const msg = JSON.parse(event.data) as Record<string, unknown>
          messageCallback?.(msg)
        } catch {
          // 忽略非 JSON 消息
        }
      }

      ws.onclose = () => {
        connected = false
        stopHeartbeat()
        disconnectCallback?.()
        scheduleReconnect()
      }

      ws.onerror = () => {}
    })
  }

  function send(data: unknown) {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(typeof data === 'string' ? data : JSON.stringify(data))
    }
  }

  function destroy() {
    destroyed = true
    stopHeartbeat()
    if (reconnectTimer) {
      clearTimeout(reconnectTimer)
      reconnectTimer = null
    }
    if (ws) {
      ws.onclose = null
      ws.onerror = null
      ws.onmessage = null
      ws.onopen = null
      ws.close()
      ws = null
    }
    connected = false
    disconnectCallback = null
    messageCallback = null
  }

  return {
    connect,
    send,
    destroy,
    onMessage: (cb) => { messageCallback = cb },
    onDisconnect: (cb) => { disconnectCallback = cb },
    isConnected: () => connected,
  }
}
