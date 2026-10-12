import { afterEach, describe, expect, it, vi } from 'vitest';
import { AskStreamError, api } from './api';

// 断线续传循环(夜审 A6 + AskStreamError 恢复句柄):fetch 全桩,真 ReadableStream。
// 服务端契约(test_analytics_ask_replay.py):重连携 askId+lastEventId 只补
// seq>last 的帧不重算 —— 本册钉客户端行为:重试体带句柄、最终失败抛
// AskStreamError(帧不丢)、首连无 askId 立即抛裸错、resume 参数首连即带。

const encoder = new TextEncoder();

function sse(chunks: string[], askId: string | null = 'ask_x1', broken = false) {
  // pull 式交付:已入队块先读到位,队列耗尽才 error/close —— start() 里直接
  // error 会按 spec 丢弃未读块,失真于真网络(已送达字节在断开前已可读)
  let delivered = false;
  return {
    ok: true,
    status: 200,
    headers: { get: (k: string) => (k.toLowerCase() === 'x-ask-id' ? askId : null) },
    body: new ReadableStream({
      pull(controller) {
        if (!delivered) {
          for (const c of chunks) controller.enqueue(encoder.encode(c));
          delivered = true;
          return;
        }
        if (broken) controller.error(new TypeError('network error'));
        else controller.close();
      },
    }),
    text: async () => chunks.join(''),
  } as unknown as Response;
}

const frame1 = 'id: 1\nevent: clarify\ndata: {"question":"选谁?"}\n\n';
const frame2 = 'id: 2\nevent: result\ndata: {"metric":"volume"}\n\n';

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('api.ask 断线续传', () => {
  it('中断后重试体携带 askId+lastEventId,成功返回全量帧无重复', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(sse([frame1], 'ask_x1', true))
      .mockResolvedValueOnce(sse([frame2]));
    vi.stubGlobal('fetch', fetchMock);

    const frames = await api.ask('本月销量');
    expect(frames.map((f) => f.id)).toEqual([1, 2]);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    const retryBody = JSON.parse(String(fetchMock.mock.calls[1][1].body));
    expect(retryBody).toMatchObject({ question: '本月销量', askId: 'ask_x1', lastEventId: 1 });
  });

  it('3 次仍断:抛 AskStreamError,askId/lastEventId/已收帧不丢', async () => {
    const fetchMock = vi.fn().mockResolvedValue(sse([frame1], 'ask_x1', true));
    vi.stubGlobal('fetch', fetchMock);

    let caught: unknown;
    try {
      await api.ask('本月销量');
    } catch (err) {
      caught = err;
    }
    expect(caught).toBeInstanceOf(AskStreamError);
    const streamErr = caught as AskStreamError;
    expect(streamErr.askId).toBe('ask_x1');
    expect(streamErr.lastEventId).toBe(1);
    expect(streamErr.frames).toHaveLength(1);
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it('首连未回 X-Ask-Id 即断:抛裸错(无句柄不可恢复),不重试', async () => {
    const fetchMock = vi.fn().mockResolvedValue(sse([frame1], null, true));
    vi.stubGlobal('fetch', fetchMock);

    let caught: unknown;
    try {
      await api.ask('本月销量');
    } catch (err) {
      caught = err;
    }
    expect(caught).not.toBeInstanceOf(AskStreamError);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('resume 参数:首连即带 askId+lastEventId(恢复结果按钮入口)', async () => {
    const fetchMock = vi.fn().mockResolvedValue(sse([frame2]));
    vi.stubGlobal('fetch', fetchMock);

    await api.ask('本月销量', undefined, undefined, { askId: 'ask_r1', lastEventId: 7 });
    const body = JSON.parse(String(fetchMock.mock.calls[0][1].body));
    expect(body).toMatchObject({ askId: 'ask_r1', lastEventId: 7 });
  });
});
