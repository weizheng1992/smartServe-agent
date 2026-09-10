// 仲裁留痕一致性 scorer(工单01 留痕列 × 工单03 案例二)
// 断言:留痕 method 非空、candidates 为非空数组(各层提议在档)、
// 留痕 winner 与终局 intents[0].intent 同源 —— 留痕必须如实反映终局,
// 而非另一套叙事。winner 断言与具体意图无关(LLM 终局意图可有方差,
// 但留痕与终局的同源性不许漂)。
export default function (output: string) {
  let parsed: any;
  try {
    parsed = JSON.parse(output);
  } catch {
    return { pass: false, score: 0, reason: 'Output is not valid JSON' };
  }
  const a = parsed.arbitration || {};
  const winner = a.winner;
  const first = (parsed.intents || [])[0]?.intent;
  if (!a.method || !Array.isArray(a.candidates) || a.candidates.length === 0) {
    return {
      pass: false,
      score: 0,
      reason: `arbitration trace incomplete: method=${a.method}, candidates=${JSON.stringify(a.candidates)}`,
    };
  }
  if (winner !== first) {
    return {
      pass: false,
      score: 0,
      reason: `trace winner ${winner} !== terminal intents[0] ${first}`,
    };
  }
  return { pass: true, score: 1, reason: `trace consistent: method=${a.method}, winner=${winner}` };
}
