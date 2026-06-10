import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { createWsClient } from '../libs/ws-client.js';

describe('createWsClient', () => {
  let client;

  beforeEach(() => {
    client = createWsClient('ws://localhost:8765');
  });

  afterEach(() => {
    if (client && client.destroy) {
      client.destroy();
    }
  });

  it('初始状态为未连接', () => {
    expect(client.isConnected()).toBe(false);
  });

  it('连接后状态更新', async () => {
    await client.connect();
    expect(client.isConnected()).toBe(true);
  });

  it('连接后可发送 JSON 消息', async () => {
    await client.connect();
    client.send({ type: 'heartbeat', ts: 12345 });
    const ws = client._getWs();
    expect(ws._sent.length).toBe(1);
    expect(JSON.parse(ws._sent[0]).type).toBe('heartbeat');
  });

  it('通过 onMessage 接收消息', async () => {
    const received = [];
    client.onMessage((msg) => received.push(msg));
    await client.connect();
    client._getWs()._receive({ type: 'result', task_id: 't1', status: 'success' });
    expect(received.length).toBe(1);
    expect(received[0].type).toBe('result');
  });

  it('按间隔发送心跳', async () => {
    vi.useFakeTimers();
    const connectPromise = client.connect();
    // Flush the MockWebSocket's setTimeout(0) to trigger onopen
    await vi.advanceTimersByTimeAsync(0);
    await connectPromise;

    const ws = client._getWs();
    ws._sent.length = 0;

    vi.advanceTimersByTime(31000);

    const heartbeats = ws._sent.map(s => JSON.parse(s)).filter(m => m.type === 'heartbeat');
    expect(heartbeats.length).toBeGreaterThan(0);
    vi.useRealTimers();
  });

  it('断开时调用 onDisconnect', async () => {
    vi.useFakeTimers();
    const handler = vi.fn();
    client.onDisconnect(handler);

    const connectPromise = client.connect();
    await vi.advanceTimersByTimeAsync(0);
    await connectPromise;

    client._getWs().close();
    expect(handler).toHaveBeenCalled();
    vi.useRealTimers();
  });
});
