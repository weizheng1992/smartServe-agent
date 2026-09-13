import React, { useCallback, useEffect, useState } from 'react';
import { adminApi } from '../../lib/api';

/**
 * 全局指标大盘(admin-readiness 03):README「全局指标大盘」承诺的实体落点。
 * 六卡 + 会话状态分布条,全部来自 GET /api/overview 库内真算(real-data-only),
 * 无在线状态数据源,故以「人工接管会话数」替代 README 原「在线客服坐席」假指标。
 */

interface OverviewData {
  activeTenants: number;
  sessions: { total: number; distribution: Record<string, number> };
  threads: { distribution: Record<string, number>; humanTakeover: number };
  approvals: { waiting: number; oldestWaitingMinutes: number };
  usage: { tokens: number; costUsd: number };
  autopilotRate: number;
  llm24h: { calls: number; costUsd: number; avgLatencyMs: number };
}

const SESSION_STATUS_META: Array<{ key: string; label: string; color: string }> = [
  { key: 'resolved_auto', label: '自动解决', color: 'bg-emerald-500' },
  { key: 'waiting_approval', label: '待审批', color: 'bg-amber-500' },
  { key: 'failed', label: '失败', color: 'bg-rose-500' },
  { key: 'rejected', label: '已驳回', color: 'bg-pink-500' },
  { key: 'cancelled', label: '已取消', color: 'bg-slate-400' },
  { key: 'llm_circuit_breaker', label: 'LLM 熔断', color: 'bg-violet-500' },
  { key: 'graph_error_degraded', label: '图降级', color: 'bg-orange-500' },
];

const CARD_CLASS = 'p-4 bg-white border border-slate-200 rounded-2xl shadow-xs';
const LABEL_CLASS = 'text-[11px] text-slate-500';
const VALUE_CLASS = 'text-2xl font-bold text-slate-900 mt-1';

export function DashboardPage() {
  const [data, setData] = useState<OverviewData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [updatedAt, setUpdatedAt] = useState<string>('');

  const load = useCallback(async () => {
    try {
      const res = await adminApi.get('/api/overview');
      if (res.success && res.data) {
        setData(res.data);
        setError(null);
        setUpdatedAt(new Date().toLocaleTimeString('zh-CN'));
      } else {
        setError(res.error || '获取大盘数据失败');
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : '网络异常');
    }
  }, []);

  useEffect(() => {
    load();
    const timer = setInterval(load, 30_000);
    return () => clearInterval(timer);
  }, [load]);

  const totalSessions = data?.sessions.total ?? 0;
  const pct = (v: number | undefined) => (v === undefined ? '—' : `${(v * 100).toFixed(1)}%`);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-xs text-slate-400">
          全部指标库内真算(session_metrics / pending_approvals / threads / llm_call_logs),30 秒自动刷新
          {updatedAt && ` · 最近刷新 ${updatedAt}`}
        </p>
        <button
          type="button"
          onClick={load}
          className="text-xs text-slate-500 hover:text-slate-800 hover:bg-slate-100 px-2.5 py-1 rounded-md transition-colors cursor-pointer"
        >
          刷新
        </button>
      </div>

      {error && <div className="p-3 bg-rose-50 border border-rose-200 rounded-xl text-xs text-rose-700">{error}</div>}

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className={CARD_CLASS}>
          <div className={LABEL_CLASS}>活跃租户数(近 7 天)</div>
          <div className={VALUE_CLASS}>{(data?.activeTenants ?? 0).toLocaleString()}</div>
          <div className="text-[10px] text-slate-400 mt-0.5">有真实会话落账的业务域</div>
        </div>
        <div className={CARD_CLASS}>
          <div className={LABEL_CLASS}>Autopilot 率(AI 自动解决)</div>
          <div className="text-2xl font-bold text-emerald-600 mt-1">{pct(data?.autopilotRate)}</div>
          <div className="text-[10px] text-slate-400 mt-0.5">
            resolved_auto / 会话总数({(data?.sessions.distribution.resolved_auto ?? 0).toLocaleString()} /{' '}
            {totalSessions.toLocaleString()})
          </div>
        </div>
        <div className={CARD_CLASS}>
          <div className={LABEL_CLASS}>待审批 HITL 工单</div>
          <div
            className={`text-2xl font-bold mt-1 ${
              (data?.approvals.waiting ?? 0) > 0 ? 'text-amber-600' : 'text-slate-900'
            }`}
          >
            {(data?.approvals.waiting ?? 0).toLocaleString()}
          </div>
          <div className="text-[10px] text-slate-400 mt-0.5">
            {(data?.approvals.waiting ?? 0) > 0 ? `最老积压 ${data?.approvals.oldestWaitingMinutes} 分钟` : '无积压'}
          </div>
        </div>
        <div className={CARD_CLASS}>
          <div className={LABEL_CLASS}>Token 累计消耗</div>
          <div className={VALUE_CLASS}>{(data?.usage.tokens ?? 0).toLocaleString()}</div>
          <div className="text-[10px] text-slate-400 mt-0.5">
            成本折算 ${(data?.usage.costUsd ?? 0).toFixed(3)} USD(与计费页同源)
          </div>
        </div>
        <div className={CARD_CLASS}>
          <div className={LABEL_CLASS}>LLM 调用(近 24h)</div>
          <div className={VALUE_CLASS}>{(data?.llm24h.calls ?? 0).toLocaleString()}</div>
          <div className="text-[10px] text-slate-400 mt-0.5">
            平均延迟 {data?.llm24h.avgLatencyMs ?? 0}ms · ${(data?.llm24h.costUsd ?? 0).toFixed(3)}
          </div>
        </div>
        <div className={CARD_CLASS}>
          <div className={LABEL_CLASS}>人工接管会话</div>
          <div className={VALUE_CLASS}>{(data?.threads.humanTakeover ?? 0).toLocaleString()}</div>
          <div className="text-[10px] text-slate-400 mt-0.5">assigned_operator 非空的历史会话</div>
        </div>
      </div>

      <div className="p-4 bg-white border border-slate-200 rounded-2xl shadow-xs">
        <div className="flex items-center justify-between mb-3">
          <span className="text-xs font-semibold text-slate-700">会话状态分布(session_metrics 全量)</span>
          <span className="text-[11px] text-slate-400">共 {totalSessions.toLocaleString()} 条落账</span>
        </div>
        {totalSessions === 0 ? (
          <div className="text-xs text-slate-400 py-6 text-center">暂无会话遥测落账</div>
        ) : (
          <>
            <div className="flex h-3 rounded-full overflow-hidden gap-0.5">
              {SESSION_STATUS_META.map(({ key, color }) => {
                const n = data?.sessions.distribution[key] ?? 0;
                return n > 0 ? (
                  <div
                    key={key}
                    className={color}
                    style={{ width: `${((n / totalSessions) * 100).toFixed(2)}%` }}
                    title={`${key}: ${n}`}
                  />
                ) : null;
              })}
            </div>
            <div className="flex flex-wrap gap-x-4 gap-y-1.5 mt-3">
              {SESSION_STATUS_META.map(({ key, label, color }) => {
                const n = data?.sessions.distribution[key] ?? 0;
                return (
                  <div key={key} className="flex items-center gap-1.5 text-[11px] text-slate-600">
                    <span className={`w-2 h-2 rounded-sm ${color}`} />
                    {label}
                    <span className="font-mono text-slate-400">{n.toLocaleString()}</span>
                  </div>
                );
              })}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
export default DashboardPage;
