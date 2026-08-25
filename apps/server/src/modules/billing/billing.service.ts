import { Injectable } from '@nestjs/common';
import { getDrizzle, sessionMetrics, tenantBillingQuotas } from 'db';
import { eq, sql } from 'drizzle-orm';

export interface TenantBillingRecord {
  businessId: string;
  tenantName: string;
  totalTokens: number;
  monthlyLimitTokens: number;
  costUsd: number;
  sessionsCount: number;
  autopilotRate: number;
  billingStatus: string;
}

@Injectable()
export class BillingService {
  async getTenantUsages(): Promise<TenantBillingRecord[]> {
    const drizzle = getDrizzle();

    // 1. 获取所有配置了配额的商户或具有 metrics 的商户
    const quotas = await drizzle.select().from(tenantBillingQuotas);
    const quotaMap = new Map<string, number>();
    for (const q of quotas) {
      quotaMap.set(q.businessId, q.monthlyLimitTokens);
    }

    // 2. 汇总 session_metrics 物理表中的 Token 和 Cost
    const metrics = await drizzle
      .select({
        businessId: sessionMetrics.businessId,
        totalTokens: sql<number>`coalesce(sum(${sessionMetrics.totalTokens}), 0)`,
        costUsd: sql<number>`coalesce(sum(${sessionMetrics.calculatedCostUsd}), 0.0)`,
        sessionsCount: sql<number>`count(${sessionMetrics.id})`,
        autoResolvedCount: sql<number>`coalesce(sum(case when ${sessionMetrics.resolutionStatus} = 'resolved_auto' then 1 else 0 end), 0)`,
      })
      .from(sessionMetrics)
      .groupBy(sessionMetrics.businessId);

    const bizSet = new Set<string>([...quotaMap.keys(), ...metrics.map((m) => m.businessId)]);

    if (bizSet.size === 0) {
      bizSet.add('nike');
      bizSet.add('adidas');
      bizSet.add('ecommerce');
    }

    const metricMap = new Map<string, (typeof metrics)[0]>();
    for (const m of metrics) {
      metricMap.set(m.businessId, m);
    }

    const result: TenantBillingRecord[] = [];

    for (const biz of bizSet) {
      const limit = quotaMap.get(biz) || 5000000;
      const m = metricMap.get(biz);
      const totalTokens = m ? Number(m.totalTokens) || 0 : 0;
      const costUsd = m ? Number(m.costUsd) || 0 : 0;
      const sessionsCount = m ? Number(m.sessionsCount) || 0 : 0;
      const autoCount = m ? Number(m.autoResolvedCount) || 0 : 0;
      const autopilotRate = sessionsCount > 0 ? Number((autoCount / sessionsCount).toFixed(2)) : 0.95;

      const usageRate = limit > 0 ? totalTokens / limit : 0;
      const billingStatus = usageRate >= 1.0 ? 'exceeded' : usageRate >= 0.8 ? 'warning' : 'normal';

      result.push({
        businessId: biz,
        tenantName:
          biz === 'nike'
            ? 'Nike 官方旗舰店'
            : biz === 'adidas'
              ? 'Adidas 运动专营'
              : biz === 'ecommerce'
                ? '通用电商主站'
                : `${biz.toUpperCase()} 商户`,
        totalTokens,
        monthlyLimitTokens: limit,
        costUsd,
        sessionsCount,
        autopilotRate,
        billingStatus,
      });
    }

    return result;
  }

  async updateQuota(businessId: string, limitTokens: number): Promise<TenantBillingRecord> {
    const drizzle = getDrizzle();

    await drizzle
      .insert(tenantBillingQuotas)
      .values({
        businessId,
        monthlyLimitTokens: limitTokens,
        updatedAt: new Date(),
      })
      .onConflictDoUpdate({
        target: tenantBillingQuotas.businessId,
        set: {
          monthlyLimitTokens: limitTokens,
          updatedAt: new Date(),
        },
      });

    // 重新拉取该商户最新账单与度量
    const allUsages = await this.getTenantUsages();
    const found = allUsages.find((u) => u.businessId === businessId);
    if (found) return found;

    return {
      businessId,
      tenantName: `${businessId.toUpperCase()} 商户`,
      totalTokens: 0,
      monthlyLimitTokens: limitTokens,
      costUsd: 0,
      sessionsCount: 0,
      autopilotRate: 1.0,
      billingStatus: 'normal',
    };
  }
}
