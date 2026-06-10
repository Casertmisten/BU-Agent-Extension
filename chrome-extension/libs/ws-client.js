export function createWsClient(url, options = {}) {
  const heartbeatInterval = options.heartbeatInterval || 30000;
  const reconnectBaseDelay = options.reconnectBaseDelay || 1000;

  let ws = null;
  let connected = false;
  let heartbeatTimer = null;
  let reconnectTimer = null;
  let reconnectAttempts = 0;
  let messageCallback = null;
  let disconnectCallback = null;
  let destroyed = false;

  function startHeartbeat() {
    stopHeartbeat();
    heartbeatTimer = setInterval(() => {
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'heartbeat', ts: Date.now() / 1000 }));
      }
    }, heartbeatInterval);
  }

  function stopHeartbeat() {
    if (heartbeatTimer) {
      clearInterval(heartbeatTimer);
      heartbeatTimer = null;
    }
  }

  function scheduleReconnect() {
    if (destroyed) return;
    const delay = Math.min(reconnectBaseDelay * Math.pow(2, reconnectAttempts), 30000);
    reconnectAttempts++;
    reconnectTimer = setTimeout(() => connect(), delay);
  }

  function connect() {
    return new Promise((resolve) => {
      ws = new WebSocket(url);

      ws.onopen = () => {
        connected = true;
        reconnectAttempts = 0;
        startHeartbeat();
        resolve();
      };

      ws.onmessage = (event) => {
        try {
          const msg = JSON.parse(event.data);
          if (messageCallback) messageCallback(msg);
        } catch {
          // ignore non-JSON
        }
      };

      ws.onclose = () => {
        connected = false;
        stopHeartbeat();
        if (disconnectCallback) disconnectCallback();
        scheduleReconnect();
      };

      ws.onerror = () => {};
    });
  }

  function send(data) {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(typeof data === 'string' ? data : JSON.stringify(data));
    }
  }

  function destroy() {
    destroyed = true;
    stopHeartbeat();
    if (reconnectTimer) {
      clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
    if (ws) {
      ws.onclose = null;
      ws.onerror = null;
      ws.onmessage = null;
      ws.onopen = null;
      ws.close();
      ws = null;
    }
    connected = false;
    disconnectCallback = null;
    messageCallback = null;
  }

  return {
    connect,
    send,
    destroy,
    onMessage: (cb) => { messageCallback = cb; },
    onDisconnect: (cb) => { disconnectCallback = cb; },
    isConnected: () => connected,
    _getWs: () => ws,
  };
}
