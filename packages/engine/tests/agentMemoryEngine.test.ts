import { describe, expect, test } from 'bun:test';
import { AgentMemoryEngine } from '../src/memory/agentMemoryEngine';
import { ContextAssemblyPipeline } from '../src/memory/contextAssemblyPipeline';

describe('AgentMemoryEngine & ContextAssemblyPipeline Unit Tests', () => {
  test('Should gather context across all 4 memory tiers in parallel', async () => {
    const memoryEngine = new AgentMemoryEngine('test_thread_engine_001', 'test_user_engine_001');

    const context = await memoryEngine.gatherContext('退货与退款偏好');

    expect(Array.isArray(context.shortMessages)).toBe(true);
    expect(Array.isArray(context.longFacts)).toBe(true);
    expect(Array.isArray(context.episodicEvents)).toBe(true);
    expect(context.taskState).toBeDefined();
  });

  test('Should record turn options across short, long, task, and episodic memory', async () => {
    const memoryEngine = new AgentMemoryEngine('test_thread_engine_002', 'test_user_engine_002');

    await memoryEngine.recordTurn({
      userQuery: '我不喜欢红色，请推荐蓝色的卫衣',
      assistantResponse: '好的，已为您筛选出蓝色卫衣列表。',
      taskState: {
        goal: '查找蓝色卫衣',
        subtasks: [
          {
            id: 's1',
            description: '筛选商品',
            status: 'completed',
          },
        ],
        currentStepIndex: 1,
      },
      episodicEvent: {
        content: '用户明确表示避开红色商品偏好',
        importance: 8,
      },
    });

    const contextAfter = await memoryEngine.gatherContext('卫衣颜色偏好');
    expect(contextAfter.shortMessages.length).toBeGreaterThan(0);
  });

  test('ContextAssemblyPipeline should format and assemble structured context bundle with token budgeting', async () => {
    const bundle = await ContextAssemblyPipeline.assemble({
      threadId: 'test_thread_pipeline_001',
      userId: 'test_user_pipeline_001',
      query: '查询鞋类商品',
      shortMessages: [
        { role: 'user', content: '您好，想买一双慢跑鞋' },
        { role: 'assistant', content: '请问您的预算和尺码是多少？' },
      ],
      ragDocs: [
        {
          title: 'Nike 跑鞋尺码对照表',
          content: '美码 9 码对应欧码 42.5 码，鞋内长 270mm。',
          score: 0.92,
        },
      ],
    });

    expect(bundle).toBeDefined();
    expect(bundle.conversationHistoryText).toContain('想买一双慢跑鞋');
    expect(bundle.ragKnowledgeText).toContain('Nike 跑鞋尺码对照表');
    expect(bundle.fullPromptContext).toContain('【知识库参考文档 (Retrieved Knowledge Base)】');
    expect(bundle.tokenCountEstimate).toBeGreaterThan(0);
  });
});
