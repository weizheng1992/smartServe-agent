import { ChatOpenAI } from '@langchain/openai';

export default async function (output: string, context: any) {
  try {
    const customerQuestion = context.vars.input;
    const expectedRules = context.vars.expectedRules || 'Be polite, express in Chinese, follow standard support SOP.';

    const judge = new ChatOpenAI({
      configuration: {
        baseURL: 'http://localhost:11211/api/openai/v1',
      },
      apiKey: 'dummy',
      modelName: 'gemini-3.5-flash:latest',
      temperature: 0,
    });

    const judgePrompt = `You are a meticulous Customer Support Quality Assurance (QA) Judge.
Evaluate the following Customer Support Assistant's reply against the Customer's Question and the strictly enforced Business SOP Rules.

Customer Question: "${customerQuestion}"
ENFORCED BUSINESS SOP RULES: "${expectedRules}"
ASSISTANT'S REPLY TO EVALUATE: "${output}"

Perform a thorough evaluation across the following dimensions:
1. Chinese Expression & Politeness (Professional, helpful, polite, native Chinese phrasing)
2. Zero Hallucinations (No fabricated tracking numbers, delivery dates, or refund statuses; state unknown if not verified)
3. SOP Compliance (Strictly follows the business policies, e.g. refunds window, membership status, etc.)

Assign a final float score between 0.0 (unacceptable, buggy, hallucinated) and 1.0 (perfect compliance, extremely professional, polite, accurate).
Provide your review output in JSON format with two keys: "score" (float) and "reason" (brief string explaining your rationale).
Do NOT include markdown backticks or text outside of the JSON.`;

    const response = await judge.invoke(judgePrompt);
    const content = typeof response === 'string' ? response : (response as any).content || '';

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
    return {
      pass: score >= 0.8,
      score,
      reason: parsedJudge.reason || 'Evaluated by LLM Judge',
    };
  } catch (err: any) {
    return { pass: false, score: 0.0, reason: `Error in answerQuality LLM-as-a-judge scorer: ${err.message}` };
  }
}
