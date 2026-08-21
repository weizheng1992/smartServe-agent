import { beforeAll, describe, expect, it } from 'bun:test';
import { getPgPool } from '../src/client';
import { tenantConfigs, tenantMembers, tenantTools, tenants, users } from '../src/schema';
import {
  addTenantMember,
  createTenant,
  getTenant,
  getTenantConfig,
  getTenantMembers,
  getTenantTools,
  saveTenantConfig,
  saveTenantTool,
} from '../src/services/tenantService';

describe('Phase 1: Tenant Management & IAM Service (TDD)', () => {
  const testBusinessId = `test_biz_${Date.now()}`;
  let createdTenantId: string;
  let testUserId: string;

  beforeAll(async () => {
    const pool = getPgPool();
    // Ensure tables exist or are created
    await pool.query(`
      CREATE TABLE IF NOT EXISTS tenants (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        business_id TEXT UNIQUE NOT NULL,
        name TEXT NOT NULL,
        plan_tier TEXT DEFAULT 'free' NOT NULL,
        status TEXT DEFAULT 'active' NOT NULL,
        created_at TIMESTAMP DEFAULT NOW()
      );
      CREATE TABLE IF NOT EXISTS tenant_members (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
        user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        role TEXT NOT NULL,
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

    // Create a mock user
    const userRes = await pool.query(`
      INSERT INTO users (id, email, created_at)
      VALUES (gen_random_uuid(), 'tenant_owner_${Date.now()}@test.com', NOW())
      RETURNING id;
    `);
    testUserId = userRes.rows[0].id;
  });

  it('should create a new tenant with businessId and default free plan', async () => {
    const tenant = await createTenant({
      businessId: testBusinessId,
      name: 'Test Tenant Store',
      planTier: 'pro',
    });

    expect(tenant).toBeDefined();
    expect(tenant.id).toBeDefined();
    expect(tenant.businessId).toBe(testBusinessId);
    expect(tenant.name).toBe('Test Tenant Store');
    expect(tenant.planTier).toBe('pro');
    expect(tenant.status).toBe('active');

    createdTenantId = tenant.id;
  });

  it('should retrieve tenant by businessId', async () => {
    const tenant = await getTenant(testBusinessId);
    expect(tenant).not.toBeNull();
    expect(tenant?.id).toBe(createdTenantId);
    expect(tenant?.businessId).toBe(testBusinessId);
  });

  it('should add a tenant member with owner role and query members', async () => {
    const membership = await addTenantMember({
      tenantId: createdTenantId,
      userId: testUserId,
      role: 'owner',
    });

    expect(membership).toBeDefined();
    expect(membership.tenantId).toBe(createdTenantId);
    expect(membership.userId).toBe(testUserId);
    expect(membership.role).toBe('owner');

    const members = await getTenantMembers(createdTenantId);
    expect(members.length).toBeGreaterThanOrEqual(1);
    expect(members.some((m) => m.userId === testUserId && m.role === 'owner')).toBe(true);
  });

  it('should save draft config and retrieve published vs draft config', async () => {
    // 1. Save draft config
    const draftConfig = await saveTenantConfig({
      businessId: testBusinessId,
      systemPrompt: 'You are an elite Nike customer support assistant.',
      welcomeMessage: 'Welcome to Nike official customer support!',
      temperature: 0.3,
      status: 'draft',
    });

    expect(draftConfig.status).toBe('draft');
    expect(draftConfig.systemPrompt).toContain('Nike');

    // 2. Query draft config
    const fetchedDraft = await getTenantConfig(testBusinessId, 'draft');
    expect(fetchedDraft).not.toBeNull();
    expect(fetchedDraft?.systemPrompt).toBe('You are an elite Nike customer support assistant.');

    // 3. Publish config
    const publishedConfig = await saveTenantConfig({
      businessId: testBusinessId,
      systemPrompt: 'You are an elite Nike customer support assistant (PUBLISHED).',
      welcomeMessage: 'Welcome to Nike official customer support!',
      temperature: 0.3,
      status: 'published',
    });

    expect(publishedConfig.status).toBe('published');

    // 4. Query published config
    const fetchedPublished = await getTenantConfig(testBusinessId, 'published');
    expect(fetchedPublished?.systemPrompt).toContain('PUBLISHED');
  });

  it('should register dynamic tenant tools and retrieve them', async () => {
    const tool = await saveTenantTool({
      tenantId: createdTenantId,
      name: 'fetch_custom_erp_order',
      description: 'Queries order status from custom merchant ERP',
      schema: {
        type: 'object',
        properties: { orderId: { type: 'string' } },
        required: ['orderId'],
      },
      authType: 'bearer',
      encryptedCredentials: 'iv_hex:tag_hex:cipher_hex',
      requiresApproval: false,
    });

    expect(tool.id).toBeDefined();
    expect(tool.name).toBe('fetch_custom_erp_order');
    expect(tool.requiresApproval).toBe(false);

    const tools = await getTenantTools(createdTenantId);
    expect(tools.length).toBeGreaterThanOrEqual(1);
    expect(tools.some((t) => t.name === 'fetch_custom_erp_order')).toBe(true);
  });
});
