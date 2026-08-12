import { describe, expect, test } from "bun:test";
import { CircuitBreaker } from "../src/llm/callLLMWithRetry";

describe("CircuitBreaker Unit Tests", () => {
  test("Should start in CLOSED state", () => {
    const cb = new CircuitBreaker();
    expect(cb.isOpen()).toBe(false);
    expect(cb.getStatus().state).toBe("CLOSED");
  });

  test("Should transition to OPEN after max failures", () => {
    const cb = new CircuitBreaker();
    for (let i = 0; i < 4; i++) {
      cb.recordFailure();
      expect(cb.isOpen()).toBe(false);
    }
    // 5th failure triggers OPEN
    cb.recordFailure();
    expect(cb.isOpen()).toBe(true);
    expect(cb.getStatus().state).toBe("OPEN");
  });

  test("Should reset to CLOSED on success", () => {
    const cb = new CircuitBreaker();
    cb.recordFailure();
    cb.recordFailure();
    cb.recordSuccess();
    expect(cb.getStatus().state).toBe("CLOSED");
    expect(cb.getStatus().failureCount).toBe(0);
  });
});
