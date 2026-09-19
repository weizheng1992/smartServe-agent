// SSE 帧解析(data agent ask 流;从 api.ask 内联循环抽出,便于单测)。

export interface SseFrame {
  event: string;
  data: any;
}

/** 解析完整 text/event-stream 为帧序列:非 data 行忽略;坏 JSON 跳过(不中断流);
 *  无 event 前缀的 data 帧忽略。与网关 `_sse()` 帧格式一一对应。 */
export function parseSseFrames(text: string): SseFrame[] {
  const frames: SseFrame[] = [];
  let event = '';
  for (const line of text.split('\n')) {
    if (line.startsWith('event: ')) {
      event = line.slice(7).trim();
    } else if (line.startsWith('data: ') && event) {
      try {
        frames.push({ event, data: JSON.parse(line.slice(6)) });
      } catch {
        // 跳过坏帧
      }
      event = '';
    }
  }
  return frames;
}

/** 增量式帧解析器(逐块喂网络字节,凑齐完整帧即回调;流式渲染用)。 */
export function createFrameParser(onFrame: (f: SseFrame) => void): (chunk: string) => void {
  let buffer = '';
  return (chunk: string) => {
    buffer += chunk;
    let sep = buffer.indexOf('\n\n');
    while (sep >= 0) {
      const block = buffer.slice(0, sep);
      buffer = buffer.slice(sep + 2);
      let event = '';
      let data: any;
      for (const line of block.split('\n')) {
        if (line.startsWith('event: ')) event = line.slice(7).trim();
        else if (line.startsWith('data: ') && event) {
          try {
            data = JSON.parse(line.slice(6));
          } catch {
            // 跳过坏帧
          }
        }
      }
      if (event && data !== undefined) onFrame({ event, data });
      sep = buffer.indexOf('\n\n');
    }
  };
}
