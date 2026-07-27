import { describe, expect, test } from 'bun:test';
import { StateGraph } from '@langchain/langgraph';
import { AgentStateAnnotation, buildHistoryContext } from '../src/graph/state';

describe('LangGraph State Reducers & History Context Sanitization', () => {
  describe('buildHistoryContext Sanitization', () => {
    test('filters out null, undefined, empty, and stringified null/undefined content', () => {
      const dirtyHistory = [
        { role: 'user', content: 'hello' },
        { role: 'assistant', content: undefined },
        { role: 'assistant', content: null },
        { role: 'assistant', content: 'undefined' },
        { role: 'assistant', content: 'null' },
        { role: 'assistant', content: '   ' },
        { role: 'assistant', content: 'My name is Assistant' },
      ];

      const sanitized = buildHistoryContext(dirtyHistory);

      // It should only preserve the valid messages and map role names
      expect(sanitized).toBe('Customer: "hello"\nAgent: "My name is Assistant"');
    });

    test('returns empty string if shortMemory is empty or undefined', () => {
      expect(buildHistoryContext([])).toBe('');
      expect(buildHistoryContext(null as any)).toBe('');
    });
  });

  describe('AgentStateAnnotation State Progression & History', () => {
    test('LangGraph compiles state and updates it properly with custom reducers', async () => {
      // Create a simplified workflow to simulate State Graph transitions
      const workflow = new StateGraph(AgentStateAnnotation)
        .addNode('nodeA', (state) => {
          return {
            history: [{ role: 'user', content: 'hello' }],
            taskPlan: {
              goal: 'A goal',
              subtasks: [{ id: '1', description: 'Step A', status: 'pending' as const }],
              currentStepIndex: 0,
            },
            loopCount: 1,
          };
        })
        .addNode('nodeB', (state) => {
          return {
            history: [{ role: 'assistant', content: 'how can I help?' }],
            taskPlan: {
              currentStepIndex: 1,
              subtasks: [{ id: '1', description: 'Step A', status: 'completed' as const }],
            },
            loopCount: state.loopCount + 1,
          };
        });

      workflow.addEdge('__start__', 'nodeA');
      workflow.addEdge('nodeA', 'nodeB');
      workflow.addEdge('nodeB', '__end__');

      const app = workflow.compile();

      // Trigger the graph execution
      const result = await app.invoke({
        threadId: 'test_thread',
        userId: 'test_user',
        input: 'initiate',
      });

      // Assert final state results
      expect(result.threadId).toBe('test_thread');
      expect(result.userId).toBe('test_user');
      expect(result.loopCount).toBe(2);

      // Test Suggestion 1: Check that history is correctly aggregated by reducer (x.concat(y))
      expect(result.history.length).toBe(2);
      expect(result.history[0]).toEqual({ role: 'user', content: 'hello' });
      expect(result.history[1]).toEqual({ role: 'assistant', content: 'how can I help?' });

      // Check taskPlan reducer merged partial updates correctly
      expect(result.taskPlan.goal).toBe('A goal');
      expect(result.taskPlan.currentStepIndex).toBe(1);
      expect(result.taskPlan.subtasks.length).toBe(1);
      expect(result.taskPlan.subtasks[0].status).toBe('completed');
    });
  });
});
