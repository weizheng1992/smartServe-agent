import { Injectable, NotFoundException } from '@nestjs/common';
import { getDrizzle, guardrailRules } from 'db';
import { and, desc, eq, or } from 'drizzle-orm';

export interface GuardrailRuleItem {
  id: string;
  tenantId?: string;
  ruleName: string;
  ruleType: 'sensitive_keyword' | 'sql_injection' | 'prompt_leakage' | string;
  pattern: string;
  action: 'block' | 'mask' | 'warn' | 'escalate_hitl' | string;
  severity: 'high' | 'medium' | 'low' | string;
  isEnabled: boolean;
  updatedAt: string;
}

@Injectable()
export class GuardrailsService {
  async getRules(tenantId?: string): Promise<GuardrailRuleItem[]> {
    const drizzle = getDrizzle();
    const cond =
      tenantId && tenantId !== 'all'
        ? or(eq(guardrailRules.businessId, tenantId), eq(guardrailRules.businessId, 'all'))
        : undefined;

    const query = cond
      ? drizzle.select().from(guardrailRules).where(cond).orderBy(desc(guardrailRules.createdAt))
      : drizzle.select().from(guardrailRules).orderBy(desc(guardrailRules.createdAt));

    const rows = await query;
    return (rows || []).map((r) => ({
      id: r.id,
      tenantId: r.businessId,
      ruleName: r.ruleName,
      ruleType: r.ruleType,
      pattern: r.pattern,
      action: r.action,
      severity: r.severity,
      isEnabled: r.isEnabled ?? true,
      updatedAt: r.updatedAt ? new Date(r.updatedAt).toISOString().split('T')[0] : '2026-02-23',
    }));
  }

  async createRule(rule: Partial<GuardrailRuleItem>, tenantId?: string): Promise<GuardrailRuleItem> {
    const drizzle = getDrizzle();
    const id = rule.id || `gr_${Date.now()}`;
    const [inserted] = await drizzle
      .insert(guardrailRules)
      .values({
        id,
        businessId: rule.tenantId || tenantId || 'all',
        ruleName: rule.ruleName || '未命名安全规则',
        ruleType: rule.ruleType || 'sensitive_keyword',
        pattern: rule.pattern || '',
        action: rule.action || 'block',
        severity: rule.severity || 'high',
        isEnabled: rule.isEnabled !== undefined ? rule.isEnabled : true,
      })
      .returning();

    return {
      id: inserted.id,
      tenantId: inserted.businessId,
      ruleName: inserted.ruleName,
      ruleType: inserted.ruleType,
      pattern: inserted.pattern,
      action: inserted.action,
      severity: inserted.severity,
      isEnabled: inserted.isEnabled ?? true,
      updatedAt: inserted.updatedAt
        ? new Date(inserted.updatedAt).toISOString().split('T')[0]
        : new Date().toISOString().split('T')[0],
    };
  }

  async updateRule(id: string, updates: Partial<GuardrailRuleItem>, tenantId?: string): Promise<GuardrailRuleItem> {
    const drizzle = getDrizzle();
    const cond =
      tenantId && tenantId !== 'all'
        ? and(
            eq(guardrailRules.id, id),
            or(eq(guardrailRules.businessId, tenantId), eq(guardrailRules.businessId, 'all')),
          )
        : eq(guardrailRules.id, id);

    const [updated] = await drizzle
      .update(guardrailRules)
      .set({
        ...(updates.ruleName ? { ruleName: updates.ruleName } : {}),
        ...(updates.ruleType ? { ruleType: updates.ruleType } : {}),
        ...(updates.pattern ? { pattern: updates.pattern } : {}),
        ...(updates.action ? { action: updates.action } : {}),
        ...(updates.severity ? { severity: updates.severity } : {}),
        ...(updates.isEnabled !== undefined ? { isEnabled: updates.isEnabled } : {}),
        updatedAt: new Date(),
      })
      .where(cond)
      .returning();

    if (!updated) {
      throw new NotFoundException({
        code: 'GUARDRAIL_RULE_NOT_FOUND',
        message: `Guardrail rule '${id}' not found in database`,
      });
    }

    return {
      id: updated.id,
      tenantId: updated.businessId,
      ruleName: updated.ruleName,
      ruleType: updated.ruleType,
      pattern: updated.pattern,
      action: updated.action,
      severity: updated.severity,
      isEnabled: updated.isEnabled ?? true,
      updatedAt: updated.updatedAt
        ? new Date(updated.updatedAt).toISOString().split('T')[0]
        : new Date().toISOString().split('T')[0],
    };
  }

  async deleteRule(id: string, tenantId?: string): Promise<boolean> {
    const drizzle = getDrizzle();
    const cond =
      tenantId && tenantId !== 'all'
        ? and(
            eq(guardrailRules.id, id),
            or(eq(guardrailRules.businessId, tenantId), eq(guardrailRules.businessId, 'all')),
          )
        : eq(guardrailRules.id, id);

    const res = await drizzle.delete(guardrailRules).where(cond).returning();
    if (!res || res.length === 0) {
      throw new NotFoundException({
        code: 'GUARDRAIL_RULE_NOT_FOUND',
        message: `Guardrail rule '${id}' not found in database`,
      });
    }
    return true;
  }
}
