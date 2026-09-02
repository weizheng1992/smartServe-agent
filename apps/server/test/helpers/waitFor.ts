/** 轮询等待谓词为真或超时(默认 5s),Phase 1 事件流投递为毫秒级异步 */
export async function waitFor(predicate: () => boolean, timeoutMs = 5000, stepMs = 25): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (predicate()) return;
    await new Promise((r) => setTimeout(r, stepMs));
  }
  throw new Error(`waitFor 超时(${timeoutMs}ms)`);
}
