import { describe, expect, it } from "bun:test";
import { isSafeUrl } from "../src/openapi/ssrfGuard";
import { createDynamicHttpTool } from "../src/openapi/dynamicToolFactory";
import { encryptSecret } from "../src/crypto/secrets";

describe("Phase 3: Dynamic OpenAPI Tools & SSRF Sandbox (TDD)", () => {
  describe("SSRF Protection Guard", () => {
    it("should block private IP ranges, localhost and cloud metadata endpoints", async () => {
      const blockedUrls = [
        "http://localhost:3000/api/internal",
        "http://127.0.0.1:8080/admin",
        "http://10.0.1.5/api/order",
        "http://172.16.0.10/secrets",
        "http://192.168.1.1/gateway",
        "http://169.254.169.254/latest/meta-data/",
        "http://0.0.0.0:5000",
      ];

      for (const url of blockedUrls) {
        const check = await isSafeUrl(url);
        expect(check.safe).toBe(false);
      }
    });

    it("should allow safe public HTTPS domain endpoints", async () => {
      const publicUrls = [
        "https://api.github.com/users",
        "https://httpbin.org/get",
        "https://api.example.com/v1/orders",
      ];

      for (const url of publicUrls) {
        const check = await isSafeUrl(url);
        expect(check.safe).toBe(true);
      }
    });
  });

  describe("Dynamic HTTP Tool Execution", () => {
    const tenantId = "nike_store";
    const masterKey =
      "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef";
    const bearerToken = "my-secret-erp-bearer-token";
    const encryptedCreds = encryptSecret(bearerToken, masterKey, tenantId);

    it("should construct a dynamic tool with schema and execute safe mocked request", async () => {
      // Mock global fetch for deterministic unit testing
      const originalFetch = globalThis.fetch;
      globalThis.fetch = async (
        input: RequestInfo | URL,
        init?: RequestInit,
      ) => {
        return new Response(
          JSON.stringify({
            status: "delivered",
            orderId: "ORD-9999",
            carrier: "FedEx",
            authorization: (init?.headers as any)?.Authorization || "",
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        );
      };

      try {
        const dynamicTool = createDynamicHttpTool({
          name: "custom_erp_query",
          description: "Fetch order from custom ERP",
          method: "POST",
          url: "https://api.example.com/v1/orders",
          authType: "bearer",
          encryptedCredentials: encryptedCreds,
          tenantId,
          masterKey,
          schema: {
            type: "object",
            properties: {
              orderId: { type: "string" },
            },
            required: ["orderId"],
          },
          requiresApproval: false,
        });

        expect(dynamicTool.name).toBe("custom_erp_query");
        expect(dynamicTool.description).toBe("Fetch order from custom ERP");
        expect(dynamicTool.requiresApproval).toBe(false);

        // Execute tool
        const result = await dynamicTool.execute({ orderId: "ORD-9999" });
        expect(result).toBeDefined();
        expect(result.success).toBe(true);
        expect(result.data).toBeDefined();
        expect((result.data as any).status).toBe("delivered");
        // Verify sensitive authorization header was redacted/masked
        expect(["[REDACTED]", "******"]).toContain(
          (result.data as any).authorization,
        );
      } finally {
        globalThis.fetch = originalFetch;
      }
    });

    it("should intercept SSRF attempt and prevent network execution", async () => {
      const maliciousTool = createDynamicHttpTool({
        name: "malicious_internal_probe",
        description: "Attempts SSRF against 127.0.0.1",
        method: "GET",
        url: "http://127.0.0.1:6379/keys",
        tenantId,
        schema: { type: "object", properties: {} },
      });

      const result = await maliciousTool.execute({});
      expect(result.success).toBe(false);
      expect(result.error).toContain("SSRF");
    });
  });
});
