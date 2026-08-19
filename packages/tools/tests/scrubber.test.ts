import { describe, expect, test } from "bun:test";
import { scrubPii, scrubPiiString } from "../src/scrubber";

describe("PII Scrubber Unit Tests", () => {
  test("Masks Chinese Phone Numbers", () => {
    const raw = "我的手机号是 13812345678，请联系我。";
    const scrubbed = scrubPiiString(raw);
    expect(scrubbed).toBe("我的手机号是 138****5678，请联系我。");
  });

  test("Masks Chinese ID Cards", () => {
    const raw = "身份证号：110101199003072345";
    const scrubbed = scrubPiiString(raw);
    expect(scrubbed).toBe("身份证号：110101********2345");
  });

  test("Masks Emails and Bank Cards", () => {
    const raw = "邮箱 alice.smith@domain.com，卡号 6222021234567890";
    const scrubbed = scrubPiiString(raw);
    expect(scrubbed).toContain("@domain.com");
    expect(scrubbed).not.toContain("alice.smith");
    expect(scrubbed).toContain("6222********7890");
  });

  test("Recursively scrubs nested objects and arrays", () => {
    const input = {
      user: {
        name: "张三",
        phone: "13987654321",
        emails: ["test.user@company.cn"],
      },
      secret: "my_password_123",
      password: "topsecretpass",
    };

    const result = scrubPii(input);
    expect(result.user.phone).toBe("139****4321");
    expect(result.user.emails[0]).toContain("@company.cn");
    expect(result.password).toBe("******");
  });
});
