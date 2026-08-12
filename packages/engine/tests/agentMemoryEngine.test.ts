import { describe, expect, test } from "bun:test";
import { AgentMemoryEngine } from "../src/memory/agentMemoryEngine";

describe("AgentMemoryEngine Facade Unit Tests", () => {
  test("Should gather context across all 4 memory tiers in parallel", async () => {
    const memoryEngine = new AgentMemoryEngine(
      "test_thread_engine_001",
      "test_user_engine_001",
    );

    const context = await memoryEngine.gatherContext("退货与退款偏好");

    expect(Array.isArray(context.shortMessages)).toBe(true);
    expect(Array.isArray(context.longFacts)).toBe(true);
    expect(Array.isArray(context.episodicEvents)).toBe(true);
    expect(context.taskState).toBeDefined();
  });

  test("Should record turn options across short, long, task, and episodic memory", async () => {
    const memoryEngine = new AgentMemoryEngine(
      "test_thread_engine_002",
      "test_user_engine_002",
    );

    await memoryEngine.recordTurn({
      userQuery: "我不喜欢红色，请推荐蓝色的卫衣",
      assistantResponse: "好的，已为您筛选出蓝色卫衣列表。",
      taskState: {
        goal: "查找蓝色卫衣",
        subtasks: [
          {
            id: "s1",
            description: "筛选商品",
            status: "completed",
          },
        ],
        currentStepIndex: 1,
      },
      episodicEvent: {
        content: "用户明确表示避开红色商品偏好",
        importance: 8,
      },
    });

    const contextAfter = await memoryEngine.gatherContext("卫衣颜色偏好");
    expect(contextAfter.shortMessages.length).toBeGreaterThan(0);
  });
});
