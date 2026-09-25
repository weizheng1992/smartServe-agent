// 锚点误吞获救断言(intent-arbitration 06,2026-09-10):
// 输入被 Step 2 判定 4 的 oos 锚句(29 条余弦 ×0.86 硬阈值)高分命中,但语义
// 上是业务内请求 —— 断言其不被「超出服务范围」罐头回复关闭:终局意图不得为
// out_of_scope,triage 输出不得含罐头文案。锚点层只提议,终局由结构化精判
// 裁决(分类器对「买个东西怎么买」判 shopping_guide/general_query,非 oos)。
export default function (output: string) {
  try {
    let parsed: any;
    try {
      parsed = JSON.parse(output);
    } catch {
      const match = output.match(/\{[\s\S]*\}/);
      if (!match) return { pass: false, score: 0.0, reason: 'Output is not valid JSON' };
      parsed = JSON.parse(match[0]);
    }

    const intents: string[] = (parsed.intents || []).map((i: any) => i?.intent).filter(Boolean);
    const text = String(parsed.output || '');

    if (intents.includes('out_of_scope')) {
      return {
        pass: false,
        score: 0.0,
        reason: `终局意图含 out_of_scope(${JSON.stringify(intents)}),锚点误吞未被 LLM 仲裁获救`,
      };
    }
    if (/超出了我的服务范围/.test(text)) {
      return {
        pass: false,
        score: 0.0,
        reason: 'triage 输出为 oos 罐头回复,会话被锚点层判死(06 之前的旧行为)',
      };
    }
    return {
      pass: true,
      score: 1.0,
      reason: `锚点 oos 命中被仲裁改判,未罐头关会话;终局意图:${JSON.stringify(intents)}`,
    };
  } catch (err: any) {
    return { pass: false, score: 0.0, reason: `Error in notOosCanned scorer: ${err.message}` };
  }
}
