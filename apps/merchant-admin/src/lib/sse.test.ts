import { describe, expect, it } from 'vitest';
import { createFrameParser, parseSseFrames } from './sse';

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

describe('createFrameParser(增量)', () => {
  const framesOf = (chunks: string[]) => {
    const got: Array<{ event: string; data: any }> = [];
    const parse = createFrameParser((f) => got.push(f));
    for (const c of chunks) parse(c);
    return got;
  };

  it('整块到达:与 parseSseFrames 等价', () => {
    const text = 'event: start\ndata: {"a":1}\n\nevent: result\ndata: {"b":2}\n\n';
    expect(framesOf([text])).toEqual(parseSseFrames(text));
  });

  it('字节级撕裂到达:跨块凑齐帧不丢不重', () => {
    const got = framesOf([
      'event: sta', 'rt\ndata: {"a"', ':1}\n\nevent: res', 'ult\ndata: {"b":2}\n\n',
    ]);
    expect(got).toEqual([
      { event: 'start', data: { a: 1 } },
      { event: 'result', data: { b: 2 } },
    ]);
  });

  it('尾部半帧保留等待后续块,不误发', () => {
    const got = framesOf(['event: result\ndata: {"b":', '2}\n\n']);
    expect(got).toEqual([{ event: 'result', data: { b: 2 } }]);
  });
});
