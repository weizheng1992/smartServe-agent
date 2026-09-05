import React, { useEffect, useState } from 'react';
import { Card, CardContent } from 'ui';
import { billingApi } from '../../../lib/api';

interface BillingStats {
  totalTokens: number;
  totalCostUsd: number;
  autopilotRate: number;
}

/** 顶部统计卡:从 /api/billing/usages 真实数据实时汇总(无数据或接口失败显示空态) */
export function BillingStatsSummary() {
  const [stats, setStats] = useState<BillingStats | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await billingApi.listTenantUsages();
        if (!cancelled && res.success && Array.isArray(res.data)) {
          const rows = res.data as any[];
          setStats({
            totalTokens: rows.reduce((sum, r) => sum + (r.totalTokens || 0), 0),
            totalCostUsd: rows.reduce((sum, r) => sum + (r.costUsd || 0), 0),
            autopilotRate:
              rows.length === 0 ? 0 : rows.reduce((sum, r) => sum + (r.autopilotRate ?? 0), 0) / rows.length,
          });
        }
      } catch (err) {
        console.warn('Failed to fetch billing usages for stats summary:', err);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
      <Card className="p-4 bg-white border-slate-200 shadow-xs">
        <CardContent className="p-0">
          <div className="text-xs font-semibold text-slate-500">全平台本月 Token 总消耗</div>
          <div className="text-2xl font-bold text-slate-900 mt-1">
            {stats ? stats.totalTokens.toLocaleString() : '—'}
          </div>
          <div className="text-[11px] text-slate-400 mt-1">按租户计量数据实时汇总</div>
        </CardContent>
      </Card>
      <Card className="p-4 bg-white border-slate-200 shadow-xs">
        <CardContent className="p-0">
          <div className="text-xs font-semibold text-slate-500">本月模型总费用支出</div>
          <div className="text-2xl font-bold text-emerald-600 mt-1">
            {stats ? `$${stats.totalCostUsd.toFixed(3)} USD` : '—'}
          </div>
          <div className="text-[11px] text-emerald-600 font-medium mt-1">按调用量实时统计</div>
        </CardContent>
      </Card>
      <Card className="p-4 bg-white border-slate-200 shadow-xs">
        <CardContent className="p-0">
          <div className="text-xs font-semibold text-slate-500">全自动解决率 (Autopilot)</div>
          <div className="text-2xl font-bold text-blue-600 mt-1">
            {stats ? `${(stats.autopilotRate * 100).toFixed(1)}%` : '—'}
          </div>
          <div className="text-[11px] text-slate-400 mt-1">无需人工客服介入率(租户均值)</div>
        </CardContent>
      </Card>
    </div>
  );
}
