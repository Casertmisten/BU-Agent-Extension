globalThis.__TEST__ = true;

global.chrome = {
  runtime: {
    sendMessage: () => {},
    onMessage: {
      addListener: () => {},
      removeListener: () => {},
    },
    getURL: (path) => `chrome-extension://mock-id/${path}`,
  },
  scripting: {
    executeScript: () => Promise.resolve(),
  },
  tabs: {
    query: () => Promise.resolve([{ id: 1, windowId: 1 }]),
    update: () => Promise.resolve(),
    onUpdated: {
      addListener: () => {},
      removeListener: () => {},
    },
    captureVisibleTab: () => Promise.resolve('data:image/png;base64,mock'),
  },
  debugger: {
    attach: () => {},
    sendCommand: () => {},
    detach: () => {},
  },
  alarms: {
    create: () => {},
    onAlarm: { addListener: () => {} },
  },
  sidePanel: { setOptions: () => {} },
};

class MockWebSocket {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSING = 2;
  static CLOSED = 3;

  constructor(url) {
    this.url = url;
    this.readyState = MockWebSocket.CONNECTING;
    this.onopen = null;
    this.onclose = null;
    this.onmessage = null;
    this.onerror = null;
    this._sent = [];

    setTimeout(() => {
      this.readyState = MockWebSocket.OPEN;
      if (this.onopen) this.onopen({ type: 'open' });
    }, 0);
  }

  send(data) {
    this._sent.push(data);
  }

  close() {
    this.readyState = MockWebSocket.CLOSED;
    if (this.onclose) this.onclose({ type: 'close', code: 1000 });
  }

  _receive(data) {
    if (this.onmessage) {
      this.onmessage({ data: typeof data === 'string' ? data : JSON.stringify(data) });
    }
  }
}

global.WebSocket = MockWebSocket;
global.MockWebSocket = MockWebSocket;
