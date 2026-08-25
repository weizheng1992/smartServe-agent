import { Injectable, NotFoundException } from '@nestjs/common';
import { getDrizzle, longMemoryFacts } from 'db';
import { type SQL, and, desc, eq } from 'drizzle-orm';

export interface PersonaFactItem {
  id: string;
  userId: string;
  businessId: string;
  scope?: string;
  fact: string;
  confidence: number;
  source: string;
  status: string;
  createdAt?: string;
}

@Injectable()
export class PersonasService {
  async getFacts(tenantId?: string, userId?: string): Promise<PersonaFactItem[]> {
    const drizzle = getDrizzle();
    const conditions: SQL<unknown>[] = [];
    if (tenantId && tenantId !== 'all') {
      conditions.push(eq(longMemoryFacts.businessId, tenantId));
    }
    if (userId) {
      conditions.push(eq(longMemoryFacts.userId, userId));
    }
    const rows =
      conditions.length > 0
        ? await drizzle
            .select()
            .from(longMemoryFacts)
            .where(and(...conditions))
            .orderBy(desc(longMemoryFacts.createdAt))
        : await drizzle.select().from(longMemoryFacts).orderBy(desc(longMemoryFacts.createdAt));

    return (rows || []).map((r) => ({
      id: r.id,
      userId: r.userId,
      businessId: r.businessId || 'global',
      scope: r.scope || 'tenant',
      fact: r.fact,
      confidence: r.confidence ?? 1.0,
      source: r.source || 'chat_dialogue_inference',
      status: r.status || 'approved',
      createdAt: r.createdAt ? new Date(r.createdAt).toISOString().split('T')[0] : '2026-02-23',
    }));
  }

  async createFact(data: Partial<PersonaFactItem>, tenantId?: string): Promise<PersonaFactItem> {
    const drizzle = getDrizzle();
    const [inserted] = await drizzle
      .insert(longMemoryFacts)
      .values({
        userId: data.userId || 'u_guest',
        businessId: data.businessId || tenantId || 'nike',
        scope: data.scope || 'tenant',
        fact: data.fact || '',
        confidence: data.confidence ?? 0.9,
        source: data.source || 'admin_manual_input',
        status: data.status || 'approved',
      })
      .returning();

    return {
      id: inserted.id,
      userId: inserted.userId,
      businessId: inserted.businessId || 'nike',
      scope: inserted.scope || 'tenant',
      fact: inserted.fact,
      confidence: inserted.confidence ?? 1.0,
      source: inserted.source || 'admin_manual_input',
      status: inserted.status || 'approved',
      createdAt: inserted.createdAt
        ? new Date(inserted.createdAt).toISOString().split('T')[0]
        : new Date().toISOString().split('T')[0],
    };
  }

  async updateFact(id: string, updates: Partial<PersonaFactItem>, tenantId?: string): Promise<PersonaFactItem> {
    const drizzle = getDrizzle();
    const cond =
      tenantId && tenantId !== 'all'
        ? and(eq(longMemoryFacts.id, id as any), eq(longMemoryFacts.businessId, tenantId))
        : eq(longMemoryFacts.id, id as any);

    const [updated] = await drizzle
      .update(longMemoryFacts)
      .set({
        ...(updates.fact ? { fact: updates.fact } : {}),
        ...(updates.confidence !== undefined ? { confidence: updates.confidence } : {}),
        ...(updates.status ? { status: updates.status } : {}),
      })
      .where(cond)
      .returning();

    if (!updated) {
      throw new NotFoundException({
        code: 'PERSONA_FACT_NOT_FOUND',
        message: `Persona memory fact '${id}' not found in database`,
      });
    }

    return {
      id: updated.id,
      userId: updated.userId,
      businessId: updated.businessId || 'global',
      scope: updated.scope || 'tenant',
      fact: updated.fact,
      confidence: updated.confidence ?? 1.0,
      source: updated.source || 'admin_manual_input',
      status: updated.status || 'approved',
      createdAt: updated.createdAt ? new Date(updated.createdAt).toISOString().split('T')[0] : '2026-02-23',
    };
  }

  async deleteFact(id: string, tenantId?: string): Promise<boolean> {
    const drizzle = getDrizzle();
    const cond =
      tenantId && tenantId !== 'all'
        ? and(eq(longMemoryFacts.id, id as any), eq(longMemoryFacts.businessId, tenantId))
        : eq(longMemoryFacts.id, id as any);

    const res = await drizzle.delete(longMemoryFacts).where(cond).returning();
    if (!res || res.length === 0) {
      throw new NotFoundException({
        code: 'PERSONA_FACT_NOT_FOUND',
        message: `Persona memory fact '${id}' not found in database`,
      });
    }
    return true;
  }
}
