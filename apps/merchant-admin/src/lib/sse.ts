// SSE 帧解析(data agent ask 流;从 api.ask 内联循环抽出,便于单测)。

export interface SseFrame {
  event: string;
  data: any;
}

/** 解析 text/event-stream 为帧序列:非 data 行忽略;坏 JSON 跳过(不中断流);
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
