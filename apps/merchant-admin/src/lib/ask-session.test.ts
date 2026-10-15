import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

// Ask 会话 core 单册(2026-10-15 四表面收敛):api 全桩,会话行为一次钉死 ——
// 此前这些语义只能寄生在 FloatingAgent.test 的 DOM 断言里,换一个表面就要
// 重写一遍,全屏/看板则根本没写。断线恢复语义的服务端契约由
// test_analytics_ask_replay.py 钉死,本册只钉客户端会话层。

vi.mock('@/lib/api', () => {
  class AskStreamError extends Error {
    askId: string;
    lastEventId: number;
    frames: unknown[];
    constructor(message: string, askId: string, lastEventId: number, frames: unknown[] = []) {
      super(message);
      this.name = 'AskStreamError';
      this.askId = askId;
      this.lastEventId = lastEventId;
      this.frames = frames;
    }
  }
  return {
    AskStreamError,
    api: { ask: vi.fn(), feedback: { submit: vi.fn() } },
  };
});

import type { AskFrame, SessionFrame } from '@/lib/analytics-frames';
import { AskStreamError, api } from '@/lib/api';
import { clarifyAskQuestion, createAskSession, isFeedbackTail } from './ask-session';

const askMock = api.ask as unknown as ReturnType<typeof vi.fn>;

const resultFrame = (data: Record<string, unknown> = { metric: 'volume' }): AskFrame => ({
  event: 'result',
  data,
});

/** 流式桩:帧经 onFrame 逐帧入列(与真 fetch 流同构),promise 随后 resolve。 */
function mockStream(frames: AskFrame[]) {
  askMock.mockImplementation((_q: unknown, _pc: unknown, cb: (f: AskFrame) => void) => {
    for (const f of frames) cb(f);
    return Promise.resolve(frames);
  });
}

beforeEach(() => {
  vi.clearAllMocks();
});

afterEach(() => {
  vi.useRealTimers();
});

describe('ask-session(提问与流式帧)', () => {
  it('user/pending 即时上屏(api 未返回时),busy 单飞防并发 ask', async () => {
    askMock.mockImplementation(() => new Promise(() => {}));
    const session = createAskSession({});
    void session.ask('品类GMV排行');
    expect(session.getState().frames.map((f) => f.event)).toEqual(['user', 'pending']);
    expect(session.getState().busy).toBe(true);
    await session.ask('第二问');
    expect(askMock).toHaveBeenCalledTimes(1);
  });

  it('成功:流式帧逐帧入列,heartbeat/start 不入对话流,settle 摘 pending,result 帧标注 question', async () => {
    mockStream([
      { event: 'heartbeat', data: {} } as AskFrame,
      { event: 'start', data: { staff: 'x' } } as AskFrame,
      resultFrame(),
    ]);
    const session = createAskSession({});
    await session.ask('本月销量');
    const frames = session.getState().frames;
    expect(frames.map((f) => f.event)).toEqual(['user', 'result']);
    expect(frames.find((f) => f.event === 'result')?.question).toBe('本月销量');
    expect(session.getState().busy).toBe(false);
  });

  it('空问句不出手', async () => {
    mockStream([]);
    const session = createAskSession({});
    await session.ask('   ');
    expect(askMock).not.toHaveBeenCalled();
  });
});

describe('ask-session(断线与恢复,ADR-0013 同族)', () => {
  it('断线:已流式帧保留且不重复追加,错误帧携恢复句柄(askId/lastEventId/question/pageContext)', async () => {
    const err = new AskStreamError('TypeError: network error', 'ask_x1', 3, [resultFrame()]);
    askMock.mockImplementation((_q: unknown, _pc: unknown, cb: (f: AskFrame) => void) => {
      cb({ event: 'clarify', data: { question: '选谁?' } } as AskFrame);
      return Promise.reject(err);
    });
    const session = createAskSession({ getSessionId: () => 's-1', getPageContext: () => ({ route: '/x' }) });
    await session.ask('本月销量');
    const frames = session.getState().frames;
    expect(frames.filter((f) => f.event === 'clarify')).toHaveLength(1);
    const errFrame = frames.find((f) => f.event === 'error');
    expect(errFrame?.data.resume).toEqual({
      askId: 'ask_x1',
      lastEventId: 3,
      question: '本月销量',
      pageContext: { route: '/x', sessionId: 's-1' },
    });
  });

  it('裸错误(未拿到 askId):错误帧无 resume,不可恢复', async () => {
    askMock.mockRejectedValue(new Error('boom'));
    const session = createAskSession({});
    await session.ask('本月销量');
    const errFrame = session.getState().frames.find((f) => f.event === 'error');
    expect(String(errFrame?.data.message)).toContain('boom');
    expect(errFrame?.data.resume).toBeUndefined();
  });

  it('resume:携句柄重进流只补不重算,旧错误帧连 pending 一起摘(不留失效按钮)', async () => {
    const err = new AskStreamError('TypeError: network error', 'ask_x1', 1, []);
    askMock.mockImplementationOnce(() => Promise.reject(err));
    const session = createAskSession({ getPageContext: () => ({ route: '/x' }) });
    await session.ask('本月销量');
    const errId = session.getState().frames.find((f) => f.event === 'error')!.id;
    mockStream([resultFrame({ metric: 'volume', rows: [{ a: 1 }] })]);
    await session.resume(errId);
    expect(askMock).toHaveBeenLastCalledWith('本月销量', { route: '/x' }, expect.any(Function), {
      askId: 'ask_x1',
      lastEventId: 1,
    });
    const events = session.getState().frames.map((f) => f.event);
    expect(events).toContain('result');
    expect(events).not.toContain('error');
    expect(events).not.toContain('pending');
  });

  it('resume 再失败:旧句柄摘、新句柄在(不堆「恢复结果」按钮),补投的部分帧照常上屏', async () => {
    const e1 = new AskStreamError('TypeError: network error', 'ask_x1', 1, []);
    const e2 = new AskStreamError('TypeError: network error', 'ask_x1', 2, []);
    askMock
      .mockImplementationOnce(() => Promise.reject(e1))
      .mockImplementationOnce((_q: unknown, _pc: unknown, cb: (f: AskFrame) => void) => {
        cb({ event: 'clarify', data: { question: '恢复补投的澄清帧' } } as AskFrame);
        return Promise.reject(e2);
      });
    const session = createAskSession({});
    await session.ask('本月销量');
    const errId = session.getState().frames.find((f) => f.event === 'error')!.id;
    await session.resume(errId);
    const errs = session.getState().frames.filter((f) => f.event === 'error');
    expect(errs).toHaveLength(1);
    expect(errs[0].data.resume?.lastEventId).toBe(2);
    expect(session.getState().frames.some((f) => String(f.data.question) === '恢复补投的澄清帧')).toBe(true);
  });
});

describe('ask-session(会话身份 = 多轮记忆开关)', () => {
  it('getSessionId 在:sessionId 由会话统一附加进 pageContext', async () => {
    mockStream([]);
    const session = createAskSession({ getSessionId: () => 's-9', getPageContext: () => ({ route: '/analytics' }) });
    await session.ask('本月销量');
    expect(askMock.mock.calls[0][1]).toEqual({ route: '/analytics', sessionId: 's-9' });
  });

  it('getSessionId 缺席(重放面):payload 不带 sessionId —— 服务端双闸零读零写', async () => {
    mockStream([]);
    const session = createAskSession({ getPageContext: () => ({ route: '/board', selection: [] }) });
    await session.ask('品类GMV排行');
    const pc = askMock.mock.calls[0][1] as Record<string, unknown> | undefined;
    expect(pc).toEqual({ route: '/board', selection: [] });
    expect(pc && 'sessionId' in pc).toBe(false);
  });
});

describe('ask-session(反馈闩锁,反馈闭环 v3.1)', () => {
  const ratedResult = () => resultFrame({ traceId: 'tr_x', metric: 'volume' });

  it('乐观置 rated → 提交载荷正确 → 闩锁释放', async () => {
    const submit = vi.fn().mockResolvedValue({ success: true });
    mockStream([ratedResult()]);
    const session = createAskSession({ submitFeedback: submit });
    await session.ask('本月销量');
    const rid = session.getState().frames.find((f) => f.event === 'result')!.id;
    const p = session.rate(rid, 'up');
    expect(session.getState().rateBusyId).toBe(rid);
    await p;
    expect(submit).toHaveBeenCalledWith({ traceId: 'tr_x', verdict: 'up', note: undefined });
    expect(session.getState().frames.find((f) => f.id === rid)?.rated).toBe('up');
    expect(session.getState().rateBusyId).toBeNull();
  });

  it('失败:回滚 + 「反馈失败」错误帧上屏(诚实呈现)', async () => {
    const submit = vi.fn().mockRejectedValue(new Error('network down'));
    mockStream([ratedResult()]);
    const session = createAskSession({ submitFeedback: submit });
    await session.ask('本月销量');
    const rid = session.getState().frames.find((f) => f.event === 'result')!.id;
    await session.rate(rid, 'up');
    expect(session.getState().frames.find((f) => f.id === rid)?.rated).toBeUndefined();
    expect(
      session.getState().frames.some((f) => f.event === 'error' && String(f.data.message).includes('反馈失败')),
    ).toBe(true);
  });

  it('rate 单飞:在途第二击被拒(防双击)', async () => {
    const submit = vi.fn().mockImplementation(() => new Promise(() => {}));
    mockStream([ratedResult()]);
    const session = createAskSession({ submitFeedback: submit });
    await session.ask('本月销量');
    const rid = session.getState().frames.find((f) => f.event === 'result')!.id;
    void session.rate(rid, 'up');
    await session.rate(rid, 'down');
    expect(submit).toHaveBeenCalledTimes(1);
  });
});

describe('ask-session(历史持久化)', () => {
  it('构造时 load 回放且 id 续排;reset 非空→空立即落盘空数组;空→空不写', async () => {
    const save = vi.fn();
    const load = vi.fn(() => [{ id: 7, event: 'user', data: { message: '昨天的提问' } } as SessionFrame]);
    const session = createAskSession({ history: { load, save } });
    expect(session.getState().frames).toHaveLength(1);
    mockStream([resultFrame()]);
    await session.ask('新问');
    expect(session.getState().frames.some((f) => f.id > 7)).toBe(true);
    session.reset();
    expect(save).toHaveBeenCalledWith([]);
    session.reset();
    expect(save).toHaveBeenCalledTimes(1);
  });

  it('落盘防抖合流一次;flush 立即写尾帧', async () => {
    vi.useFakeTimers();
    const save = vi.fn();
    const session = createAskSession({ history: { load: () => null, save }, debounceMs: 800 });
    mockStream([resultFrame()]);
    await session.ask('一');
    expect(save).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(800);
    expect(save).toHaveBeenCalledTimes(1);
    expect(save.mock.calls[0][0].map((f: SessionFrame) => f.event)).toEqual(['user', 'result']);
    session.flush();
    expect(save).toHaveBeenCalledTimes(2);
  });
});

describe('ask-session(replace 重放语义:看板刷新)', () => {
  it('旧帧保留至成功才整轮换(刷新中途不闪空);失败还原旧面 + 错误帧', async () => {
    mockStream([resultFrame({ metric: 'old' })]);
    const session = createAskSession({});
    await session.ask('旧问', { replace: true });
    expect(session.getState().frames.map((f) => f.event)).toEqual(['result']);

    // 失败:还原旧面(旧结果保留)+ 错误帧
    askMock.mockRejectedValueOnce(new Error('gateway down'));
    await session.ask('再问', { replace: true });
    expect(session.getState().frames.map((f) => f.event)).toEqual(['result', 'error']);

    // 在途:旧结果仍在(不闪空),busy 闸立起;成功整轮换(旧 error 一并消失)
    let deliver!: (f: AskFrame) => void;
    let release!: () => void;
    askMock.mockImplementation((_q: unknown, _pc: unknown, cb: (f: AskFrame) => void) => {
      deliver = cb;
      return new Promise<void>((r) => {
        release = r;
      });
    });
    const inflight = session.ask('新问', { replace: true });
    expect(session.getState().frames.some((f) => f.event === 'result' && f.data.metric === 'old')).toBe(true);
    expect(session.getState().busy).toBe(true);
    deliver(resultFrame({ metric: 'new' }));
    release();
    await inflight;
    expect(session.getState().frames.map((f) => f.event)).toEqual(['result']);
    expect(session.getState().frames[0].data.metric).toBe('new');
  });
});

describe('ask-session(纯函数)', () => {
  it('isFeedbackTail:同 traceId 只在组尾出按钮;无 traceId 不渲染', () => {
    const f = (traceId?: string) => ({ event: 'result', data: traceId ? { traceId } : {} }) as AskFrame;
    const frames = [f('a'), f('a'), f('b'), f()];
    expect(isFeedbackTail(frames, 0)).toBe(false);
    expect(isFeedbackTail(frames, 1)).toBe(true);
    expect(isFeedbackTail(frames, 2)).toBe(true);
    expect(isFeedbackTail(frames, 3)).toBe(false);
  });

  it('clarifyAskQuestion:指标歧义模板 / 实体反问原问组合 / 无原问退选项名', () => {
    expect(clarifyAskQuestion({}, { label: '销量' })).toBe('按销量的商品排行');
    expect(
      clarifyAskQuestion({ clarifyKind: 'entity', originalQuestion: '有个活动卖得怎么样' }, { label: '开学季满减' }),
    ).toBe('有个活动卖得怎么样(开学季满减)');
    expect(clarifyAskQuestion({ clarifyKind: 'entity' }, { label: '开学季满减' })).toBe('开学季满减');
  });
});
