import { describe, expect, it } from 'vitest';
import { parseSseFrames } from './sse';

describe('parseSseFrames', () => {
  it('解析 event+data 成帧,多帧保序', () => {
    const text = 'event: start\ndata: {"staff":"老板"}\n\nevent: result\ndata: {"metric":"gmv","rows":[]}\n\n';
    const frames = parseSseFrames(text);
    expect(frames).toEqual([
      { event: 'start', data: { staff: '老板' } },
      { event: 'result', data: { metric: 'gmv', rows: [] } },
    ]);
  });

  it('坏 JSON 跳过不中断后续帧', () => {
    const text = 'event: a\ndata: {bad json}\nevent: b\ndata: {"ok":1}\n\n';
    expect(parseSseFrames(text)).toEqual([{ event: 'b', data: { ok: 1 } }]);
  });

  it('无 event 前缀的 data 行与非 SSE 行忽略', () => {
    const text = ': keep-alive comment\ndata: {"orphan":true}\nevent: c\ndata: {"x":1}\n';
    expect(parseSseFrames(text)).toEqual([{ event: 'c', data: { x: 1 } }]);
  });

  it('空输入返回空数组', () => {
    expect(parseSseFrames('')).toEqual([]);
  });
});
