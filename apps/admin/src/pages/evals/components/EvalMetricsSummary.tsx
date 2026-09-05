import React, { useEffect, useState } from 'react';
import { Card, CardContent } from 'ui';
import { evalsApi } from '../../../lib/api';

interface EvalStats {
  toolAccuracy: number;
  ragFaithfulness: number;
  hitlTriggerRate: number;
}

/** 顶部指标卡:从 /api/evals/results 记录求均值。
 *  注意:评测记录由本地随机生成器写入(isMock: true),非真实评测 —— 真实评测走 bun run test:prompt。 */
export function EvalMetricsSummary() {
  const [stats, setStats] = useState<EvalStats | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await evalsApi.getResults();
        if (!cancelled && res.success && Array.isArray(res.data)) {
          const rows = res.data as any[];
          const avg = (pick: (r: any) => number | undefined) =>
            rows.length === 0 ? 0 : rows.reduce((sum, r) => sum + (pick(r) ?? 0), 0) / rows.length;
          setStats({
            toolAccuracy: avg((r) => r.toolAccuracy),
            ragFaithfulness: avg((r) => r.ragFaithfulness),
            hitlTriggerRate: avg((r) => r.hitlTriggerRate),
          });
        }
      } catch (err) {
        console.warn('Failed to fetch eval results for metrics summary:', err);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const pct = (v: number | undefined) => (stats ? `${(v! * 100).toFixed(1)}%` : '—');

  return (
    <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
      <Card className="p-4 bg-white border-slate-200 shadow-xs">
        <CardContent className="p-0">
          <div className="text-xs font-semibold text-slate-500">平均工具调用准确率</div>
          <div className="text-2xl font-bold text-slate-900 mt-1">{pct(stats?.toolAccuracy)}</div>
          <div className="text-[11px] text-slate-400 mt-1">全部评测批次均值</div>
        </CardContent>
      </Card>
      <Card className="p-4 bg-white border-slate-200 shadow-xs">
        <CardContent className="p-0">
          <div className="text-xs font-semibold text-slate-500">RAG 知识检索忠实度</div>
          <div className="text-2xl font-bold text-slate-900 mt-1">{pct(stats?.ragFaithfulness)}</div>
          <div className="text-[11px] text-blue-600 font-medium mt-1">Contextual Retrieval 增益</div>
        </CardContent>
      </Card>
      <Card className="p-4 bg-white border-slate-200 shadow-xs">
        <CardContent className="p-0">
          <div className="text-xs font-semibold text-slate-500">自动拦截/HITL 触发率</div>
          <div className="text-2xl font-bold text-amber-600 mt-1">{pct(stats?.hitlTriggerRate)}</div>
          <div className="text-[11px] text-slate-400 font-medium mt-1">数据源 isMock,真实评测走 test:prompt</div>
        </CardContent>
      </Card>
    </div>
  );
}
