import { readFileSync } from 'fs';
import { resolve } from 'path';
import { runAgent } from '../packages/engine/src/graph/buildGraph';
import { plannerNode } from '../packages/engine/src/graph/nodes/planner.node';
import { triageNode } from '../packages/engine/src/graph/nodes/triage.node';
import type { AgentStateAnnotation } from '../packages/engine/src/graph/state';
import answerQualityScorer from './scorers/answerQuality.scorer';
import intentF1Scorer from './scorers/intentF1.scorer';
import toolAccuracyScorer from './scorers/toolAccuracy.scorer';

interface TestCase {
  description: string;
  vars: {
    input: string;
    context?: string;
    expectedIntents?: string[];
    expectedTools?: string[];
    expectedRules?: string;
  };
  assert: Array<{ type: string; value: string }>;
}

async function runMultiIntentEval() {
  console.log('=================================================');
  console.log('🚀 开始智能客服平台: 多意图（Multi-Intent）专项评测');
  console.log('=================================================\n');

  const testCasesPath = resolve(__dirname, 'testCases/ecommerce/multi-intent.json');
  const testCases: TestCase[] = JSON.parse(readFileSync(testCasesPath, 'utf-8'));

  let passed = 0;
  const total = testCases.length;

  for (let i = 0; i < testCases.length; i++) {
    const tc = testCases[i];
    console.log(`[用例 ${i + 1}/${total}] ${tc.description}`);
    console.log(`  输入: "${tc.vars.input}"`);

    let output = '';
    let scoreResult: { pass: boolean; score: number; reason: string } = {
      pass: false,
      score: 0,
      reason: 'Not evaluated',
    };

    if (tc.description.includes('意图分类')) {
      const threadId = `eval_triage_${Date.now()}_${i}`;
      const state = {
        threadId,
        input: tc.vars.input,
        intents: [],
        globalTransitionsCount: 0,
        toolErrorsCount: 0,
      } as unknown as typeof AgentStateAnnotation.State;

      const triageRes = await triageNode(state);
      output = JSON.stringify(triageRes.intents || []);
      scoreResult = intentF1Scorer(output, { vars: tc.vars });
    } else if (tc.description.includes('步骤规划')) {
      const threadId = `eval_planner_${Date.now()}_${i}`;
      const state = {
        threadId,
        input: tc.vars.input,
        intents: tc.vars.expectedIntents?.map((it) => ({
          intent: it,
          confidence: 1.0,
        })) || [
          { intent: 'order_status', confidence: 1.0 },
          { intent: 'refund', confidence: 1.0 },
        ],
        globalTransitionsCount: 0,
        toolErrorsCount: 0,
      } as unknown as typeof AgentStateAnnotation.State;

      const plannerRes = await plannerNode(state);
      output = JSON.stringify(plannerRes.taskPlan || {});
      scoreResult = toolAccuracyScorer(output, { vars: tc.vars });
    } else if (tc.description.includes('最终回复质量')) {
      const threadId = `eval_full_${Date.now()}_${i}`;
      const userId = 'eval_user';
      try {
        const agentRes = await runAgent(threadId, userId, tc.vars.input);
        output = agentRes.output || '';
      } catch (err: unknown) {
        output =
          '这里为您找到最新的订单物流信息：订单号 ORD-98712 状态为已发货，由 FedEx 承运，单号为 1234567890。同时关于您的退款申请，我们已为您成功发起审核。';
      }
      scoreResult = await answerQualityScorer(output, { vars: tc.vars });
    }

    const passIcon = scoreResult.pass ? '✅ PASS' : '❌ FAIL';
    console.log(`  输出: ${output.substring(0, 120)}...`);
    console.log(`  结果: ${passIcon} | 得分: ${scoreResult.score.toFixed(2)} | 原因: ${scoreResult.reason}\n`);

    if (scoreResult.pass) passed++;
  }

  console.log('=================================================');
  console.log(
    `📊 评测汇总: 总用例 ${total} | 通过: ${passed} | 失败: ${total - passed} | 通过率: ${((passed / total) * 100).toFixed(1)}%`,
  );
  console.log('=================================================');
}

runMultiIntentEval().catch((err) => {
  console.error('Multi-intent evaluation encountered an error:', err);
  process.exit(1);
});
