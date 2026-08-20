import { describe, expect, test } from 'bun:test';
import { plannerNode } from '../src/graph/nodes/planner.node';
import type { AgentStateAnnotation, SubTask } from '../src/graph/state';

describe('Planner Node Unit Tests', () => {
  test('General Query Fast-Path bypasses LLM and returns directPlan', async () => {
    const state: Partial<typeof AgentStateAnnotation.State> = {
      threadId: 'test_thread_general',
      intents: [{ intent: 'general_query', confidence: 1.0 }],
      input: '你好',
      globalTransitionsCount: 0,
    };

    const result = await plannerNode(state as typeof AgentStateAnnotation.State);

    expect(result).toBeDefined();
    expect(result.taskPlan).toBeDefined();
    expect(result.taskPlan.goal).toContain('Bypass planner loop');
    expect(result.taskPlan.subtasks.length).toBe(1);
    expect(result.taskPlan.subtasks[0].id).toBe('respond_general');
    expect(result.globalTransitionsCount).toBe(1);
  });

  test('Human Escalation Fast-Path bypasses LLM and returns fastPlan', async () => {
    const state: Partial<typeof AgentStateAnnotation.State> = {
      threadId: 'test_thread_escalation',
      intents: [{ intent: 'human_escalation', confidence: 1.0 }],
      input: '帮我转接人工客服处理',
      globalTransitionsCount: 0,
    };

    const result = await plannerNode(state as typeof AgentStateAnnotation.State);

    expect(result).toBeDefined();
    expect(result.taskPlan).toBeDefined();
    expect(result.taskPlan.goal).toBe('Escalate conversation to human support operator');
    expect(result.taskPlan.subtasks.length).toBe(1);
    expect(result.taskPlan.subtasks[0].id).toBe('step_fast_human_escalation');
    expect(result.globalTransitionsCount).toBe(1);
  });

  test('Order Status Fast-Path synthesizes single-step plan when Order ID is present', async () => {
    const state: Partial<typeof AgentStateAnnotation.State> = {
      threadId: 'test_thread_order_fast',
      intents: [{ intent: 'order_status', confidence: 1.0 }],
      input: '查询订单 ORD-88888 物流信息',
      globalTransitionsCount: 0,
    };

    const result = await plannerNode(state as typeof AgentStateAnnotation.State);

    expect(result).toBeDefined();
    expect(result.taskPlan).toBeDefined();
    expect(result.taskPlan.goal).toBe('Query status for order ORD-88888');
    expect(result.taskPlan.subtasks.length).toBe(1);
    expect(result.taskPlan.subtasks[0].id).toBe('step_fast_status');
    expect(result.taskPlan.subtasks[0].description).toContain('ORD-88888');
    expect(result.globalTransitionsCount).toBe(1);
  });

  test('Refund Fast-Path synthesizes single-step refund plan when Order ID is in shortMemory', async () => {
    const state: Partial<typeof AgentStateAnnotation.State> = {
      threadId: 'test_thread_refund_memory',
      intents: [{ intent: 'refund', confidence: 1.0 }],
      input: '这个订单帮我退款',
      shortMemory: [
        { role: 'user', content: '我要查订单 ORD-99999' },
        { role: 'assistant', content: '为您查到订单 ORD-99999 状态为已发货' },
      ],
      globalTransitionsCount: 0,
    };

    const result = await plannerNode(state as typeof AgentStateAnnotation.State);

    expect(result).toBeDefined();
    expect(result.taskPlan).toBeDefined();
    expect(result.taskPlan.goal).toBe('Process refund for order ORD-99999');
    expect(result.taskPlan.subtasks.length).toBe(1);
    expect(result.taskPlan.subtasks[0].id).toBe('step_fast_refund');
    expect(result.globalTransitionsCount).toBe(1);
  });

  test('Multi-Intent Fast-Path synthesizes multi-subtask plan when Order ID is present', async () => {
    const state: Partial<typeof AgentStateAnnotation.State> = {
      threadId: 'test_thread_multi_fast',
      intents: [
        {
          intent: 'order_status',
          confidence: 0.95,
          type: 'primary',
          entities: { orderId: 'ORD-77777' },
        },
        {
          intent: 'refund',
          confidence: 0.9,
          type: 'secondary',
          entities: { orderId: 'ORD-77777' },
        },
      ],
      input: '查下 ORD-77777 物流，另外帮我发起退款',
      globalTransitionsCount: 0,
    };

    const result = await plannerNode(state as typeof AgentStateAnnotation.State);

    expect(result).toBeDefined();
    expect(result.taskPlan).toBeDefined();
    expect(result.taskPlan.goal).toContain('ORD-77777');
    expect(result.taskPlan.subtasks.length).toBe(2);
    expect(result.taskPlan.subtasks[0].id).toBe('step_fast_status_0');
    expect(result.taskPlan.subtasks[1].id).toBe('step_fast_refund_1');
    expect(result.globalTransitionsCount).toBe(1);
  });
});
