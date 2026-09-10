// 咨询直答快轨 scorer(工单03 案例一)
// 断言:arbitration.method === 'rag_direct' —— 证明会话在 triage 内经
// 咨询快轨闭环直答(planner 从未运行);这是「秒级直答不进 planner」的
// 直接证据,不依赖答案文本内容(答案措辞由 answerQuality 类 scorer 管)。
export default function (output: string) {
  let parsed: any;
  try {
    parsed = JSON.parse(output);
  } catch {
    return { pass: false, score: 0, reason: 'Output is not valid JSON' };
  }
  const m = (parsed.arbitration || {}).method;
  if (m !== 'rag_direct') {
    return {
      pass: false,
      score: 0,
      reason: `expected arbitration.method=rag_direct (consult fast path bypass, planner never ran), got ${m}`,
    };
  }
  return { pass: true, score: 1, reason: 'consult fast path closed the loop pre-planner' };
}
