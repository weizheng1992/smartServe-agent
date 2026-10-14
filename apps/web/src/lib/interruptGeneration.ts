/** 打断在途回答(S2a,stream-reliability-push 02)—— C 端「停止生成」的数据面。
 *
 * 消费网关取消契约(03 号票):POST /api/chat/{jobId}/cancel → 200 受理
 * (引擎在下一个图检查点协作停止,终态 interrupted 走 result 帧)/ 404 作业
 * 已结束(竞态时 result 帧即将收口,无需本地态)/ 400/403/409 属闸拒绝面
 * (同身份调用不预期;409 为防御性分支),一律 ok:false 交由调用方兜底。
 */

export interface InterruptOutcome {
  ok: boolean;
  status: number;
}

/** 网络层失败哨兵:fetch 抛错(断网/超时)时置 0 —— 非 HTTP 语义,调用方
 * 据此与「网关明确拒绝」区分(失败时 result 帧或断线语义兜底收口)。 */
export const INTERRUPT_NETWORK_FAILURE = 0;

export type FetchLike = (
  input: string,
  init?: { method: string },
) => Promise<{
  ok: boolean;
  status: number;
}>;

export async function interruptGeneration(
  params: { jobId: string; userId: string; businessId?: string },
  fetchImpl: FetchLike = fetch as FetchLike,
): Promise<InterruptOutcome> {
  const query = new URLSearchParams({ userId: params.userId });
  if (params.businessId) query.set('businessId', params.businessId);
  try {
    const res = await fetchImpl(`/api/chat/${encodeURIComponent(params.jobId)}/cancel?${query.toString()}`, {
      method: 'POST',
    });
    return { ok: res.ok, status: res.status };
  } catch {
    // 网络层失败:不算打断成功;result 帧或断线语义(onError)兜底收口
    return { ok: false, status: INTERRUPT_NETWORK_FAILURE };
  }
}

export interface InterruptibleMessage {
  jobId?: string;
  isLoading?: boolean;
  role: string;
  content: string;
  interrupted?: boolean;
}

/** 中断终局的消息行替换:加载气泡就地转「已停止」诚实态,严禁假装修完。
 * output 原样落行 —— 函数本身支持部分输出(测试钉面),但当前 S2c 收口把
 * 中断轮部分态 output 强制为空,现网实渲染即「已停止」标记 + 无正文;
 * 引擎未来若放行部分态,此行原样承接。非目标行原样返回。 */
export function markInterrupted<T extends InterruptibleMessage>(messages: T[], jobId: string, output: string): T[] {
  return messages.map((m) =>
    m.jobId === jobId && m.isLoading
      ? { ...m, isLoading: false, role: 'assistant' as const, content: output, interrupted: true }
      : m,
  );
}
