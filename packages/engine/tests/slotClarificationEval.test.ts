import { describe, expect, it } from 'bun:test';
import { readFileSync } from 'fs';
import { resolve } from 'path';
import slotClarificationScorer from '../../../eval/scorers/slotClarification.scorer';
import { triageNode } from '../src/graph/nodes/triage.node';
import type { AgentStateAnnotation } from '../src/graph/state';

interface PromptfooCase {
  description: string;
  vars: {
    input: string;
    expectedIntent: string;
    expectedMissingSlots: string[];
    expectClarification?: boolean;
  };
}

describe('🌟 Promptfoo Evaluation Cases: Slot Clarification & Intent-Slot Machine', () => {
  const evalPath = resolve(__dirname, '../../../eval/testCases/ecommerce/slot-clarification.json');
  const testCases: PromptfooCase[] = JSON.parse(readFileSync(evalPath, 'utf-8'));

  for (const tc of testCases) {
    it(`Promptfoo Case: ${tc.description}`, async () => {
      const threadId = `eval_slot_${Date.now()}_${Math.random()}`;
      const state = {
        threadId,
        input: tc.vars.input,
        intents: [],
        globalTransitionsCount: 0,
        toolErrorsCount: 0,
      } as unknown as typeof AgentStateAnnotation.State;

      const triageRes = await triageNode(state);
      const output = JSON.stringify(triageRes.intents || []);

      const score = slotClarificationScorer(output, { vars: tc.vars });
      expect(score.pass).toBe(true);
      expect(score.score).toBeGreaterThanOrEqual(0.8);
    });
  }
});
