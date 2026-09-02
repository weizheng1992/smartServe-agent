/**
 * 📜 实时契约测试(SSE + socket.io)— Phase 0.3
 *
 * 钉死两条实时通路的线上协议,作为 gateway-py 的 1:1 复刻验收:
 *
 * 1. SSE:GET /api/chat/:jobId/stream
 *    - 响应头:text/event-stream / no-cache / keep-alive
 *    - 帧格式:`id: <seq>` + `event: <thought|cards|result>` + `data: {json}`
 *    - Last-Event-ID 重连重放(只补发 seq > lastEventId 的事件)
 *
 * 2. socket.io namespace /ws/chat:
 *    join_thread → joined_room(ack) + peer_joined(房间广播)
 *    takeover_conversation / release_takeover → conversation_state_changed
 *    send_message → new_message
 *    typing → user_typing
 *
 * 依赖密封容器环境(bunfig preload 已保证 env 先于模块求值注入)。
 */
import { afterAll, beforeAll, describe, expect, it } from 'bun:test';
import { type SealedEnv, initSealedEnv, loadDb, loadEngine } from '../helpers/sealedEnv';

let sealed: SealedEnv;
let db: typeof import('db')['db'];
let agentEventEmitter: typeof import('engine')['agentEventEmitter'];
let app: import('@nestjs/common').INestApplication;
let baseUrl: string;
let io: typeof import('socket.io-client')['io'];

const TS = Date.now();
const RT_THREAD = `rt_contract_thread_${TS}`;

/** 等待谓词为真或超时(ms) */
async function waitFor(predicate: () => boolean, timeoutMs = 5000, stepMs = 25): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (predicate()) return;
    await new Promise((r) => setTimeout(r, stepMs));
  }
  throw new Error(`waitFor 超时(${timeoutMs}ms)`);
}

beforeAll(async () => {
  sealed = await initSealedEnv();
  await sealed.seedTenants();

  ({ db } = await loadDb());
  ({ agentEventEmitter } = await loadEngine());
  ({ io } = await import('socket.io-client'));

  const { AppModule } = await import('../../src/app.module');
  const { Test } = await import('@nestjs/testing');
  const moduleFixture = await Test.createTestingModule({ imports: [AppModule] }).compile();
  app = moduleFixture.createNestApplication();
  await app.init();
  await app.listen(0); // 随机端口,真实 HTTP + socket.io 服务

  const address = app.getHttpServer().address() as { port: number };
  baseUrl = `http://127.0.0.1:${address.port}`;

  // socket.io takeover/release 会更新会话状态,需要 thread fixture
  await db.createThread(RT_THREAD, 'u_rt_contract', 'nike');
});

afterAll(async () => {
  await app.close();
});

describe('📜 Contract: SSE /api/chat/:jobId/stream', () => {
  it('响应头 + 帧格式 + id 序列符合 wire 协议', async () => {
    const jobId = `job_rt_${TS}`;
    const ac = new AbortController();
    const res = await fetch(`${baseUrl}/api/chat/${jobId}/stream`, { signal: ac.signal });
    expect(res.status).toBe(200);
    expect(res.headers.get('content-type')).toContain('text/event-stream');
    expect(res.headers.get('cache-control')).toContain('no-cache');

    let raw = '';
    const reader = res.body!.getReader();
    const decoder = new TextDecoder();
    const pump = (async () => {
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        raw += decoder.decode(value, { stream: true });
      }
    })();

    // 连接建立后灌入 2 个 thought + 1 个 result
    await new Promise((r) => setTimeout(r, 100));
    agentEventEmitter.emit('thought', { jobId, step: 'RT 契约步骤 1' });
    agentEventEmitter.emit('thought', { jobId, step: 'RT 契约步骤 2' });
    agentEventEmitter.emit('result', { jobId, output: 'RT 契约最终回答', cards: [] });

    await waitFor(() => raw.includes('event: result'), 5000);
    ac.abort();
    await pump.catch(() => {});

    // 帧格式:每个事件块含递增 id + event + data(JSON)
    const blocks = raw.split('\n\n').filter((b) => b.trim().length > 0);
    const eventBlocks = blocks.filter((b) => b.startsWith('id:'));
    expect(eventBlocks.length).toBeGreaterThanOrEqual(3);
    expect(eventBlocks[0]).toMatch(/^id: 1\nevent: thought\ndata: \{.*\}$/);
    expect(eventBlocks[1]).toMatch(/^id: 2\nevent: thought\ndata: \{.*\}$/);
    expect(eventBlocks[2]).toMatch(/^id: 3\nevent: (cards|result)\ndata: \{.*\}$/);
  });

  it('Last-Event-ID 重连仅重放缺失事件', async () => {
    const jobId = `job_rt_replay_${TS}`;
    const ac1 = new AbortController();
    const conn1 = await fetch(`${baseUrl}/api/chat/${jobId}/stream`, { signal: ac1.signal });
    conn1.body!.cancel().catch(() => {});
    ac1.abort();

    agentEventEmitter.emit('thought', { jobId, step: '重放事件 1' });
    agentEventEmitter.emit('thought', { jobId, step: '重放事件 2' });
    agentEventEmitter.emit('thought', { jobId, step: '重放事件 3' });
    await new Promise((r) => setTimeout(r, 100));

    const ac2 = new AbortController();
    const conn2 = await fetch(`${baseUrl}/api/chat/${jobId}/stream`, {
      signal: ac2.signal,
      headers: { 'last-event-id': '1' },
    });
    let raw = '';
    const reader = conn2.body!.getReader();
    const decoder = new TextDecoder();
    const pump = (async () => {
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        raw += decoder.decode(value, { stream: true });
      }
    })();

    await waitFor(() => raw.includes('id: 3'), 5000);
    ac2.abort();
    await pump.catch(() => {});

    // 只应补发 id 2、3;不得重复 id 1
    expect(raw).toContain('id: 2');
    expect(raw).toContain('id: 3');
    expect(raw).not.toContain('id: 1\n');
  });
});

describe('📜 Contract: socket.io /ws/chat', () => {
  it('五个消息事件的全链路协议', async () => {
    const client = io(`${baseUrl}/ws/chat`, {
      auth: { tenantId: 'nike', userId: 'u_rt_operator', role: 'operator' },
      transports: ['websocket'],
      reconnection: false,
    });

    const received: Array<{ event: string; payload: any }> = [];
    for (const evt of ['joined_room', 'peer_joined', 'conversation_state_changed', 'new_message', 'user_typing']) {
      client.on(evt, (payload: any) => received.push({ event: evt, payload }));
    }

    const connected = new Promise<void>((resolve, reject) => {
      client.on('connect', () => resolve());
      client.on('connect_error', (err: Error) => reject(err));
    });
    await connected;

    // 1. join_thread → joined_room ack
    const joinAck: any = await client.emitWithAck('join_thread', {
      threadId: RT_THREAD,
      tenantId: 'nike',
      role: 'operator',
      operatorId: `op_${TS}`,
      operatorName: '契约测试坐席',
    });
    expect(joinAck).toMatchObject({ threadId: RT_THREAD, tenantId: 'nike' });
    await waitFor(() => received.some((r) => r.event === 'joined_room'));

    // 2. takeover_conversation → conversation_state_changed(human_takeover)
    await client.emitWithAck('takeover_conversation', {
      threadId: RT_THREAD,
      tenantId: 'nike',
      operatorId: `op_${TS}`,
      operatorName: '契约测试坐席',
    });
    await waitFor(() =>
      received.some((r) => r.event === 'conversation_state_changed' && r.payload?.status === 'human_takeover'),
    );
    const takeoverEvent = received.find(
      (r) => r.event === 'conversation_state_changed' && r.payload?.status === 'human_takeover',
    );
    expect(takeoverEvent?.payload).toMatchObject({ operatorName: '契约测试坐席' });

    // 3. send_message → new_message
    const sendAck: any = await client.emitWithAck('send_message', {
      threadId: RT_THREAD,
      tenantId: 'nike',
      role: 'operator',
      content: '契约测试:人工坐席消息',
      operatorInfo: { operatorId: `op_${TS}`, operatorName: '契约测试坐席' },
    });
    expect(sendAck).toMatchObject({ success: true });
    await waitFor(() => received.some((r) => r.event === 'new_message'));
    const msgEvent = received.find((r) => r.event === 'new_message');
    expect(msgEvent?.payload).toHaveProperty('content', '契约测试:人工坐席消息');

    // 4. typing → user_typing
    await client.emitWithAck('typing', { threadId: RT_THREAD, tenantId: 'nike', isTyping: true });
    await waitFor(() => received.some((r) => r.event === 'user_typing'));

    // 5. release_takeover → conversation_state_changed(回收)
    await client.emitWithAck('release_takeover', { threadId: RT_THREAD, tenantId: 'nike', operatorId: `op_${TS}` });
    await waitFor(() => received.filter((r) => r.event === 'conversation_state_changed').length >= 2);

    client.disconnect();
  }, 15000);
});
