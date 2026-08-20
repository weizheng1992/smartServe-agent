import { describe, expect, it, beforeAll } from "bun:test";
import {
  createTenant,
  getTenant,
  saveTenantConfig,
  getTenantConfig,
  saveTenantTool,
  getTenantTools,
  getPgPool,
} from "db";
import {
  parseDocumentText,
  chunkDocumentText,
  prepareRagDocumentRecords,
} from "engine";

describe("Phase 5: Tenant Hub End-to-End API Logic (TDD)", () => {
  const businessId = `brand_${Date.now()}`;
  let tenantId: string;

  beforeAll(async () => {
    const pool = getPgPool();
    // Ensure all tenant tables are initialized
    await pool.query(`
      CREATE TABLE IF NOT EXISTS tenants (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        business_id TEXT UNIQUE NOT NULL,
        name TEXT NOT NULL,
        plan_tier TEXT DEFAULT 'free' NOT NULL,
        status TEXT DEFAULT 'active' NOT NULL,
        created_at TIMESTAMP DEFAULT NOW()
      );
      CREATE TABLE IF NOT EXISTS tenant_configs (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        business_id TEXT NOT NULL,
        system_prompt TEXT,
        welcome_message TEXT,
        temperature REAL DEFAULT 0.7,
        status TEXT DEFAULT 'draft' NOT NULL,
        version INTEGER DEFAULT 1 NOT NULL,
        updated_at TIMESTAMP DEFAULT NOW()
      );
      CREATE TABLE IF NOT EXISTS tenant_tools (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
        name TEXT NOT NULL,
        description TEXT,
        schema JSONB NOT NULL,
        auth_type TEXT DEFAULT 'none',
        encrypted_credentials TEXT,
        requires_approval BOOLEAN DEFAULT FALSE,
        enabled BOOLEAN DEFAULT TRUE,
        created_at TIMESTAMP DEFAULT NOW()
      );
    `);
  });

  it("should complete self-service tenant onboarding flow", async () => {
    // 1. Onboard tenant
    const tenant = await createTenant({
      businessId,
      name: "Acme Super Store",
      planTier: "enterprise",
    });

    expect(tenant.id).toBeDefined();
    expect(tenant.businessId).toBe(businessId);
    expect(tenant.planTier).toBe("enterprise");
    tenantId = tenant.id;

    // 2. Initialize default draft prompt config
    const config = await saveTenantConfig({
      businessId,
      systemPrompt: "You are the helpful AI concierge for Acme Super Store.",
      welcomeMessage: "Hello! How can Acme help you today?",
      temperature: 0.5,
      status: "draft",
    });

    expect(config.status).toBe("draft");
    expect(config.version).toBe(1);

    // 3. Register custom ERP dynamic tool
    const tool = await saveTenantTool({
      tenantId,
      name: "query_acme_inventory",
      description: "Checks real-time inventory in Acme warehouse",
      schema: {
        type: "object",
        properties: { sku: { type: "string" } },
        required: ["sku"],
      },
      authType: "custom_header",
      encryptedCredentials: "iv:tag:cipher",
      requiresApproval: false,
    });

    expect(tool.id).toBeDefined();
    expect(tool.name).toBe("query_acme_inventory");

    // 4. Ingest SOP knowledge document
    const rawDoc = "# Acme Return SOP\nItems can be returned within 14 days.";
    const parsed = await parseDocumentText({
      content: rawDoc,
      filename: "acme-sop.md",
    });
    const chunks = chunkDocumentText({
      text: parsed.rawText,
      targetChunkSize: 500,
    });
    const ragRecords = prepareRagDocumentRecords({
      businessId,
      chunks,
      contextualSummaries: ["Acme SOP explaining 14-day return rule."],
    });

    expect(ragRecords).toHaveLength(1);
    expect(ragRecords[0].businessId).toBe(businessId);
    expect(ragRecords[0].contextualSummary).toContain("14-day");

    // 5. Publish config to live
    const published = await saveTenantConfig({
      businessId,
      systemPrompt:
        "You are the helpful AI concierge for Acme Super Store (LIVE v2).",
      status: "published",
    });

    expect(published.status).toBe("published");
    const activeLive = await getTenantConfig(businessId, "published");
    expect(activeLive?.systemPrompt).toContain("LIVE v2");
  });
});
