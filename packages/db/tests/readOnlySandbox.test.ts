import { describe, expect, it } from "bun:test";
import { executeReadOnlyAnalyticsQuery } from "../src/client";

describe("🛡️ Database Read-Only Analytics Sandbox (TDD)", () => {
  it("能够成功在只读事务沙箱中执行参数化查询", async () => {
    const res = await executeReadOnlyAnalyticsQuery<{
      num: number;
      greeting: string;
    }>({
      text: "SELECT $1::int AS num, $2::text AS greeting",
      values: [42, "hello sandbox"],
    });

    expect(res).toBeDefined();
    expect(res.length).toBe(1);
    expect(res[0].num).toBe(42);
    expect(res[0].greeting).toBe("hello sandbox");
  });

  it("安全防线：在只读事务沙箱中尝试执行数据写入或表修改操作时会被物理拦截并回滚", async () => {
    // 尝试在只读事务中创建临时表或写入数据
    let errorCaught: any = null;
    try {
      await executeReadOnlyAnalyticsQuery({
        text: "INSERT INTO users (id, email) VALUES (gen_random_uuid(), 'illegal_write@test.com')",
        values: [],
      });
    } catch (err: any) {
      errorCaught = err;
    }

    expect(errorCaught).not.toBeNull();
    // PostgreSQL 会抛出 cannot execute INSERT in a read-only transaction (25006)
    expect(String(errorCaught.message).toLowerCase()).toContain("read-only");
  });
});
