// 同会话同问一致性 scorer(工单03 案例五,语义缓存一致性)
// 断言:sameOutput === true 且首答非空 —— 同线程连续两次同问,第二次经
// 语义缓存(≥0.96)须返回与首答逐字一致的直答,不得同问异答。
// 注:缓存命中分支的 intents 翻转(consult→general_query)是现行留痕行为,
// 不在本断言口径内(快轨终局权收编见工单05);一致性以用户可见输出为准。
export default function (output: string) {
  let parsed: any;
  try {
    parsed = JSON.parse(output);
  } catch {
    return { pass: false, score: 0, reason: 'Output is not valid JSON' };
  }
  if (parsed.sameOutput !== true) {
    return {
      pass: false,
      score: 0,
      reason: `same-session same-ask gave different answers (semantic cache inconsistency). firstMethod=${parsed.firstMethod}, secondMethod=${parsed.secondMethod}`,
    };
  }
  if (!parsed.firstOutput || parsed.firstOutput.length < 20) {
    return {
      pass: false,
      score: 0,
      reason: 'first answer is empty — consult fast path did not fire',
    };
  }
  return {
    pass: true,
    score: 1,
    reason: `consistent answers across same-session repeat (firstMethod=${parsed.firstMethod}, secondMethod=${parsed.secondMethod})`,
  };
}
