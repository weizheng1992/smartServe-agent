import { describe, expect, test } from 'bun:test';
import { plannerNode } from '../src/graph/nodes/planner.node';
import { StepExecutionEngine } from '../src/graph/nodes/stepExecutionEngine';
import type { AgentStateAnnotation, IntentResult, TaskPlan } from '../src/graph/state';

describe('条件分支与 DAG 依赖意图建模测试 (Conditional Intent Flow & DAG Planning)', () => {
  test('Planner 应该能为带条件的意图自动组装前置查询与带条件子任务', async () => {
    const intents: IntentResult[] = [
      {
        intent: 'order_modify_address',
        confidence: 0.95,
        type: 'primary',
        entities: { orderId: 'ORD-98712' },
        taskSpec: {
          intentType: 'order_modify_address',
          slots: { orderId: 'ORD-98712', newAddress: '北京市海淀区科技园' },
          confidence: 0.95,
          missingSlots: [],
        },
        condition: {
          field: 'shipping_status',
          operator: 'equals',
          expectedValue: 'pending',
        },
      },
    ];

    const mockState = {
      threadId: 'test_thread_cond_' + Date.now(),
      userId: 'usr_test_1001',
      input: '如果 ORD-98712 还没发货就帮我改送到北京市海淀区科技园',
      intents,
      shortMemory: [],
    } as unknown as typeof AgentStateAnnotation.State;

    const res = await plannerNode(mockState);
    expect(res.taskPlan).toBeDefined();
    expect(res.taskPlan?.subtasks.length).toBeGreaterThanOrEqual(2);
    // 第一步为前置查询
    expect(res.taskPlan?.subtasks[0].id).toContain('step_fast_status_pre');
    // 第二步为条件修改地址
    expect(res.taskPlan?.subtasks[1].condition).toBeDefined();
    expect(res.taskPlan?.subtasks[1].condition?.field).toBe('shipping_status');
  });

  test('StepExecutionEngine 遇到不满足条件的步骤时应标记为 skipped', async () => {
    const planWithUnmetCondition: TaskPlan = {
      goal: 'Conditional address modification',
      subtasks: [
        {
          id: 'step_fast_status_pre',
          description: 'Call getOrderStatus for order ORD-98712',
          status: 'completed',
          result: {
            output: {
              orderId: 'ORD-98712',
              shipping_status: 'delivered', // 实际已送达
            },
          },
        },
        {
          id: 'step_fast_change_address',
          description: 'Call changeShippingAddress for order ORD-98712 with new address 北京市海淀区科技园',
          status: 'pending',
          condition: {
            field: 'shipping_status',
            operator: 'equals',
            expectedValue: 'pending', // 要求必须是未发货
          },
        },
      ],
      currentStepIndex: 1,
    };

    const mockState = {
      threadId: 'test_thread_cond_exec_' + Date.now(),
      userId: 'usr_test_1001',
      input: '如果还没发货就改地址',
      taskPlan: planWithUnmetCondition,
      businessConfig: {
        tools: ['getOrderStatus', 'changeShippingAddress'],
      },
    } as unknown as typeof AgentStateAnnotation.State;

    const execRes = await StepExecutionEngine.executeStep(mockState);
    const modifiedStep = execRes.taskPlan.subtasks[1];

    expect(modifiedStep.status).toBe('skipped');
    expect(modifiedStep.result?.skippedReason).toContain('Condition unmet');
  });
});
