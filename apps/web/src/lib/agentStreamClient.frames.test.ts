// 帧解析契约(2026-10-02 夜审测试补强):agentStreamClient.ts 的事件分发
// 逻辑此前零覆盖(既有两例只钉构造与无 EventSource 守卫)。这里以受控
// EventSource 假体注入全局,捕Listener 后手工派发帧,钉 status 节点中文名
// 映射 / result 自闭合 / 坏 JSON 两条降级臂 / cleanup 物理断开。
import { afterEach, describe, expect, test } from 'bun:test';
import { AgentStreamClient } from './agentStreamClient';

type Handler = (event: { data?: string }) => void;

class MockEventSource {
  static instances: MockEventSource[] = [];
  url: string;
  closed = false;
  private handlers = new Map<string, Handler>();

  constructor(url: string) {
    this.url = url;
    MockEventSource.instances.push(this);
  }

  addEventListener(type: string, handler: Handler) {
    this.handlers.set(type, handler);
  }

  dispatch(type: string, data?: string) {
    this.handlers.get(type)?.({ data });
  }

  close() {
    this.closed = true;
  }
}

const installMock = () => {
  (globalThis as Record<string, unknown>).EventSource = MockEventSource;
};

afterEach(() => {
  (globalThis as Record<string, unknown>).EventSource = undefined;
  MockEventSource.instances = [];
});

describe('AgentStreamClient 帧解析契约(夜审 T9)', () => {
  test('status 帧:节点中文名映射(triage/planner/executor/validator)且原字段透传', () => {
    installMock();
    const client = new AgentStreamClient('job_frames_1');
    const seen: Array<Record<string, unknown>> = [];
    client.connect({ onStatus: (e) => seen.push(e as Record<string, unknown>) });
    const es = MockEventSource.instances.at(-1)!;
    expect(es.url).toBe('/api/chat/job_frames_1/stream');

    es.dispatch('status', JSON.stringify({ node: 'triage', tokens: 3 }));
    es.dispatch('status', JSON.stringify({ node: 'planner' }));
    es.dispatch('status', JSON.stringify({ node: 'executor' }));
    es.dispatch('status', JSON.stringify({ node: 'validator' }));
    es.dispatch('status', JSON.stringify({ node: 'mystery_node' }));
    es.dispatch('status', JSON.stringify({}));

    expect(seen.map((e) => e.nodeName)).toEqual([
      'Triage 节点',
      'Planner 节点',
      'Executor 节点',
      'Validator 节点',
      // 未登记节点保留原名(仅缺省 node 才回落 'system')
      'mystery_node',
      'system',
    ]);
    expect(seen[0]).toMatchObject({ node: 'triage', tokens: 3 });
  });

  test('result 帧:载荷回调并物理断开连接(回合终态即关流)', () => {
    installMock();
    const client = new AgentStreamClient('job_frames_2');
    const seen: unknown[] = [];
    client.connect({ onResult: (e) => seen.push(e) });
    const es = MockEventSource.instances.at(-1)!;

    es.dispatch('result', JSON.stringify({ output: '已退款', cards: [{ type: 'text' }] }));

    expect(seen[0]).toMatchObject({ output: '已退款' });
    expect(es.closed).toBe(true);
  });

  test('status 帧坏 JSON:静默降级不炸流(不回调也不抛)', () => {
    installMock();
    const client = new AgentStreamClient('job_frames_3');
    const seen: unknown[] = [];
    client.connect({ onStatus: (e) => seen.push(e) });
    const es = MockEventSource.instances.at(-1)!;

    expect(() => es.dispatch('status', '{broken')).not.toThrow();
    expect(seen).toHaveLength(0);
    expect(es.closed).toBe(false);
  });

  test('result 帧坏 JSON:回调 onError 并关流(终态解析失败必须释放连接)', () => {
    installMock();
    const client = new AgentStreamClient('job_frames_4');
    const errors: unknown[] = [];
    const results: unknown[] = [];
    client.connect({
      onResult: (e) => results.push(e),
      onError: (e) => errors.push(e),
    });
    const es = MockEventSource.instances.at(-1)!;

    expect(() => es.dispatch('result', 'not-json')).not.toThrow();
    expect(results).toHaveLength(0);
    expect(errors[0]).toBeInstanceOf(Error);

    expect(() => es.dispatch('result', 'not-json')).not.toThrow();
    expect(results).toHaveLength(0);
    expect(errors[0]).toBeInstanceOf(Error);
    expect(es.closed).toBe(true);
  });

  test('cleanup 返回的断开函数物理释放 EventSource', () => {
    installMock();
    const client = new AgentStreamClient('job_frames_5');
    const cleanup = client.connect({});
    const es = MockEventSource.instances.at(-1)!;

    cleanup();
    expect(es.closed).toBe(true);
  });
});
