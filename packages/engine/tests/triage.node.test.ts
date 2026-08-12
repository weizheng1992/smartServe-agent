import { describe, expect, test } from "bun:test";
import { triageNode } from "../src/graph/nodes/triage.node";
import type { AgentStateAnnotation } from "../src/graph/state";

describe("Triage Node Unit Tests", () => {
  test("Rule Bypass: Empty input should trigger immediate bypass", async () => {
    const threadId = `test_triage_empty_${Date.now()}`;
    const state = {
      threadId,
      input: "",
      intents: [],
      globalTransitionsCount: 0,
      toolErrorsCount: 0,
    } as unknown as typeof AgentStateAnnotation.State;

    const result = await triageNode(state);

    expect(result).toBeDefined();
    expect(result.output).toContain("空消息");
    expect(result.taskPlan).toBeDefined();
    expect(result.taskPlan?.subtasks[0].id).toBe("bypass_step");
  });

  test("Rule Bypass: Symbol-only input should trigger symbol bypass", async () => {
    const threadId = `test_triage_symbols_${Date.now()}`;
    const state = {
      threadId,
      input: "???!!!",
      intents: [],
      globalTransitionsCount: 0,
      toolErrorsCount: 0,
    } as unknown as typeof AgentStateAnnotation.State;

    const result = await triageNode(state);

    expect(result).toBeDefined();
    expect(result.output).toContain("订单、物流或退款");
    expect(result.taskPlan?.subtasks[0].id).toBe("bypass_step");
  });

  test("Rule Bypass: Greeting input should return greeting bypass response", async () => {
    const threadId = `test_triage_greeting_${Date.now()}`;
    const state = {
      threadId,
      input: "你好",
      intents: [],
      globalTransitionsCount: 0,
      toolErrorsCount: 0,
    } as unknown as typeof AgentStateAnnotation.State;

    const result = await triageNode(state);

    expect(result).toBeDefined();
    expect(result.output).toContain("智能电商客服助理");
    expect(result.intents?.[0].intent).toBe("general_query");
  });

  test("Rule Bypass: Exit input should return exit bypass response", async () => {
    const threadId = `test_triage_exit_${Date.now()}`;
    const state = {
      threadId,
      input: "再见",
      intents: [],
      globalTransitionsCount: 0,
      toolErrorsCount: 0,
    } as unknown as typeof AgentStateAnnotation.State;

    const result = await triageNode(state);

    expect(result).toBeDefined();
    expect(result.output).toContain("祝您生活愉快");
    expect(result.intents?.[0].intent).toBe("general_query");
  });

  test("Rule Match: Explicit human escalation request", async () => {
    const threadId = `test_triage_escalation_${Date.now()}`;
    const state = {
      threadId,
      input: "我要转人工客服处理",
      intents: [],
      globalTransitionsCount: 0,
      toolErrorsCount: 0,
    } as unknown as typeof AgentStateAnnotation.State;

    const result = await triageNode(state);

    expect(result).toBeDefined();
    expect(result.intents).toBeDefined();
    expect(result.intents?.[0].intent).toBe("human_escalation");
    expect(result.intents?.[0].confidence).toBe(1.0);
  });

  test("System Resume: Input starting with 'System:' should resume flow", async () => {
    const threadId = `test_triage_system_resume_${Date.now()}`;
    const state = {
      threadId,
      input: "System: Human support operator responded to the user",
      intents: [],
      globalTransitionsCount: 0,
      toolErrorsCount: 0,
    } as unknown as typeof AgentStateAnnotation.State;

    const result = await triageNode(state);

    expect(result).toBeDefined();
    expect(result.intents).toBeDefined();
    expect(result.intents?.length).toBeGreaterThan(0);
    expect(result.intents?.[0].confidence).toBe(1.0);
  });
});
