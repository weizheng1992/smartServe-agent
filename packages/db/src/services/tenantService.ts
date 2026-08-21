import { and, desc, eq } from 'drizzle-orm';
import { getDrizzle, getPgPool } from '../client';
import { tenantConfigs, tenantMembers, tenantTools, tenants } from '../schema';

export interface CreateTenantParams {
  businessId: string;
  name: string;
  planTier?: 'free' | 'pro' | 'enterprise';
}

export interface AddTenantMemberParams {
  tenantId: string;
  userId: string;
  role: 'owner' | 'admin' | 'agent';
}

export interface SaveTenantConfigParams {
  businessId: string;
  systemPrompt?: string;
  welcomeMessage?: string;
  temperature?: number;
  status: 'draft' | 'published';
}

export interface SaveTenantToolParams {
  tenantId: string;
  name: string;
  description?: string;
  schema: Record<string, unknown>;
  authType?: 'none' | 'bearer' | 'basic' | 'custom_header';
  encryptedCredentials?: string;
  requiresApproval?: boolean;
  enabled?: boolean;
}

export async function createTenant(params: CreateTenantParams) {
  const db = getDrizzle();
  const [created] = await db
    .insert(tenants)
    .values({
      businessId: params.businessId,
      name: params.name,
      planTier: params.planTier || 'free',
      status: 'active',
    })
    .returning();
  return created;
}

export async function getTenant(businessId: string) {
  const db = getDrizzle();
  const rows = await db.select().from(tenants).where(eq(tenants.businessId, businessId)).limit(1);
  return rows.length > 0 ? rows[0] : null;
}

export async function addTenantMember(params: AddTenantMemberParams) {
  const db = getDrizzle();
  const [member] = await db
    .insert(tenantMembers)
    .values({
      tenantId: params.tenantId,
      userId: params.userId,
      role: params.role,
    })
    .returning();
  return member;
}

export async function getTenantMembers(tenantId: string) {
  const db = getDrizzle();
  return await db.select().from(tenantMembers).where(eq(tenantMembers.tenantId, tenantId));
}

export async function saveTenantConfig(params: SaveTenantConfigParams) {
  const db = getDrizzle();

  // Find existing config with this businessId and status
  const existing = await db
    .select()
    .from(tenantConfigs)
    .where(and(eq(tenantConfigs.businessId, params.businessId), eq(tenantConfigs.status, params.status)))
    .orderBy(desc(tenantConfigs.version))
    .limit(1);

  if (existing.length > 0) {
    const nextVersion = (existing[0].version || 1) + 1;
    const [updated] = await db
      .update(tenantConfigs)
      .set({
        systemPrompt: params.systemPrompt !== undefined ? params.systemPrompt : existing[0].systemPrompt,
        welcomeMessage: params.welcomeMessage !== undefined ? params.welcomeMessage : existing[0].welcomeMessage,
        temperature: params.temperature !== undefined ? params.temperature : existing[0].temperature,
        version: nextVersion,
        updatedAt: new Date(),
      })
      .where(eq(tenantConfigs.id, existing[0].id))
      .returning();
    return updated;
  }

  const [created] = await db
    .insert(tenantConfigs)
    .values({
      businessId: params.businessId,
      systemPrompt: params.systemPrompt || null,
      welcomeMessage: params.welcomeMessage || null,
      temperature: params.temperature !== undefined ? params.temperature : 0.7,
      status: params.status,
      version: 1,
    })
    .returning();
  return created;
}

export async function getTenantConfig(businessId: string, status: 'draft' | 'published' = 'published') {
  const db = getDrizzle();
  const rows = await db
    .select()
    .from(tenantConfigs)
    .where(and(eq(tenantConfigs.businessId, businessId), eq(tenantConfigs.status, status)))
    .orderBy(desc(tenantConfigs.version))
    .limit(1);

  return rows.length > 0 ? rows[0] : null;
}

export async function saveTenantTool(params: SaveTenantToolParams) {
  const db = getDrizzle();
  const [tool] = await db
    .insert(tenantTools)
    .values({
      tenantId: params.tenantId,
      name: params.name,
      description: params.description || null,
      schema: params.schema,
      authType: params.authType || 'none',
      encryptedCredentials: params.encryptedCredentials || null,
      requiresApproval: params.requiresApproval ?? false,
      enabled: params.enabled ?? true,
    })
    .returning();
  return tool;
}

export async function getTenantTools(tenantId: string) {
  const db = getDrizzle();
  return await db.select().from(tenantTools).where(eq(tenantTools.tenantId, tenantId));
}
