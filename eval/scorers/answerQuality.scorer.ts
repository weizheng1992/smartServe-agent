export default async function (output: string, context: any) {
  try {
    const customerQuestion = context.vars.input;
    const expectedRules = context.vars.expectedRules || 'Be polite, express in Chinese, follow standard support SOP.';

    // Judge model/endpoint/key come from repo .env (AI_MODEL / AI_BASE_URL / AI_API_KEY,
    // loaded into process.env by promptfoo). Fail loudly when missing instead of
    // falling back to an unreachable default (the old 127.0.0.1:11211 gateway is gone).
    const judgeModel = process.env.AI_MODEL;
    const judgeBase = process.env.AI_BASE_URL;
    const judgeKey = process.env.AI_API_KEY;
    if (!judgeModel || !judgeBase || !judgeKey) {
      return {
        pass: false,
        score: 0.0,
        reason: 'answerQuality judge misconfigured: AI_MODEL / AI_BASE_URL / AI_API_KEY missing from environment',
      };
    }

    // v2 rubric(05 号票首测后收紧,2026-10-26):首测一致率 78%(21/27,<80% 不可用),
    // 六条不同意见聚类出三个 judge 盲区 —— ④指代准确性(「上一笔订单」被当当前
    // 订单,judge 放行)、⑤多模态证据透明(破损回复未陈述图识结果/未与用户确认)、
    // ⑥相关性与范围(保养问题混入门店信息)。v2 增三维 + 双段式(先逐维推理后结论)
    // + 显式 Unknown 弃权档(score=-1,证据不足严禁猜)。
    const payload = {
      model: judgeModel,
      messages: [
        {
          role: 'user',
          content: `You are a meticulous Customer Support Quality Assurance (QA) Judge.
Evaluate the Assistant's reply against the Customer's Question and the strictly enforced Business SOP Rules.

Customer Question: "${customerQuestion}"
ENFORCED BUSINESS SOP RULES: "${expectedRules}"
ASSISTANT'S REPLY TO EVALUATE: "${output}"

Evaluate across SIX dimensions:
1. Chinese Expression & Politeness (professional, helpful, native Chinese phrasing)
2. Zero Hallucinations (no fabricated tracking numbers, delivery dates, or refund statuses; state unknown if not verified)
3. SOP Compliance (refund windows, approval thresholds, membership rules, etc.)
4. Referent Accuracy (entity references must match the customer's actual referent — e.g. 「上一笔订单」 means the PREVIOUS order, which is a DIFFERENT order from any order mentioned in the current message; conflating referents is a severe error)
5. Multimodal Evidence Transparency (when the turn involves an image, the reply should state what was recognized from it and confirm consistency with the customer's claim where applicable — silent assumptions are errors)
6. Relevance & Scope (answer the question asked; padding with unrelated store/promotion/location info lowers the score)

PROCEDURE — two-phase: FIRST write your dimension-by-dimension reasoning in "reason" citing specific evidence from the reply; THEN conclude with "score" (float 0.0-1.0). If you genuinely cannot judge a dimension for lack of verifiable context, output {"score": -1, "reason": "abstain: ..."} — an explicit Unknown abstention; NEVER guess.
Output ONLY JSON with keys "reason" (string, your reasoning first) and "score" (float). No markdown backticks, no text outside the JSON.`,
        },
      ],
      temperature: 0,
    };

    const res = await fetch(`${judgeBase.replace(/\/$/, '')}/chat/completions`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${judgeKey}`,
      },
      body: JSON.stringify(payload),
    });

    if (!res.ok) {
      throw new Error(`Local judge model API returned status: ${res.status}`);
    }

    const resData = await res.json();
    const content = resData.choices?.[0].message?.content || '';

    let parsedJudge: any;
    try {
      parsedJudge = JSON.parse(content.trim());
    } catch {
      const match = content.match(/\{[\s\S]*\}/);
      if (match) {
        parsedJudge = JSON.parse(match[0]);
      } else {
        return {
          pass: false,
          score: 0.0,
          reason: `Failed to parse judge output JSON. Raw output: ${content}`,
        };
      }
    }

    const score = Number(parsedJudge.score);
    if (score === -1) {
      // Unknown 弃权档:证据不足不猜 —— 不算通过(防弃权洗白),理由带 [弃权]
      // 前缀供台账识别弃权率
      return {
        pass: false,
        score: 0.0,
        reason: `[弃权] ${parsedJudge.reason || 'judge abstained'}`,
      };
    }
    return {
      pass: score >= 0.8,
      score,
      reason: parsedJudge.reason || 'Evaluated by LLM Judge',
    };
  } catch (err: any) {
    return {
      pass: false,
      score: 0.0,
      reason: `Error in answerQuality LLM-as-a-judge scorer: ${err.message}`,
    };
  }
}
