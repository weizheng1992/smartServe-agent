'use client';

import {
  Activity,
  CheckCircle2,
  Clock,
  Cpu,
  DollarSign,
  Layers,
  Laptop,
  Loader2,
  Lock,
  RefreshCw,
  Search,
  ShieldAlert,
  Sparkles,
  TrendingUp,
  XCircle,
} from 'lucide-react';
import { useEffect, useState } from 'react';

interface Approval {
  id: string;
  threadId: string;
  actionType: string;
  actionPayload: any;
  status: 'waiting' | 'approved' | 'rejected' | 'expired' | 'cancelled';
  deadline: string;
  createdAt: string;
}

interface AnalyticsSummary {
  totalCostUsd: number;
  totalSessions: number;
  avgLatencyMs: number;
  avgTokens: number;
  autopilotRate: number;
}

export default function AdminDashboard() {
  const [selectedMerchant, setSelectedMerchant] = useState<string>('ecommerce');
  const [approvals, setApprovals] = useState<Approval[]>([]);
  const [summary, setSummary] = useState<AnalyticsSummary>({
    totalCostUsd: 0,
    totalSessions: 0,
    avgLatencyMs: 0,
    avgTokens: 0,
    autopilotRate: 100,
  });
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [rejectionReasons, setRejectionReasons] = useState<Record<string, string>>({});
  const [submittingActionId, setSubmittingActionId] = useState<string | null>(null);

  const fetchDashboardData = async () => {
    setIsRefreshing(true);
    try {
      // 1. Fetch approvals list
      const appRes = await fetch('/api/chat/approvals');
      const appData = await appRes.json();
      if (appData.success && appData.approvals) {
        setApprovals(appData.approvals);
      }

      // 2. Fetch BI metrics for selected merchant
      const anaRes = await fetch(`/api/analytics?businessId=${selectedMerchant}`);
      const anaData = await anaRes.json();
      if (anaData.success && anaData.summary) {
        setSummary(anaData.summary);
      }
    } catch (err) {
      console.error('[Dashboard Fetch Error]:', err);
    } finally {
      setIsRefreshing(false);
    }
  };

  useEffect(() => {
    fetchDashboardData();
    const interval = setInterval(fetchDashboardData, 5000); // Auto refresh every 5 seconds for high fidelity logs!
    return () => clearInterval(interval);
  }, [selectedMerchant]);

  const handleApprovalAction = async (approvalId: string, action: 'approve' | 'reject') => {
    setSubmittingActionId(approvalId);
    try {
      const reason = rejectionReasons[approvalId] || '';
      const res = await fetch('/api/chat/approvals', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          approvalId,
          action,
          rejectionReason: action === 'reject' ? reason || '退款申请不符合政策要求。' : '',
        }),
      });
      const data = await res.json();
      if (data.success) {
        // Clear input reason
        setRejectionReasons((prev) => {
          const next = { ...prev };
          delete next[approvalId];
          return next;
        });
        await fetchDashboardData();
      } else {
        alert(data.error || '审批执行失败');
      }
    } catch (err: any) {
      alert(`审批流恢复出错: ${err.message || err}`);
    } finally {
      setSubmittingActionId(null);
    }
  };

  // Filter approvals that are waiting or historical
  const pendingApprovals = approvals.filter((a) => a.status === 'waiting');
  const auditedApprovals = approvals.filter((a) => a.status !== 'waiting');

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 font-sans antialiased">
      {/* 🚀 Header */}
      <header className="px-8 py-5 border-b border-slate-800 bg-slate-900/40 backdrop-blur-md sticky top-0 z-40 flex flex-col md:flex-row justify-between items-start md:items-center gap-4">
        <div className="flex items-center space-x-3.5">
          <div className="h-10 w-10 rounded-xl bg-indigo-600 flex items-center justify-center shadow-lg shadow-indigo-500/20 shrink-0">
            <Lock className="h-5 w-5 text-white" />
          </div>
          <div>
            <h1 className="text-lg font-bold tracking-tight text-slate-200">
              smartServe 客服大盘 & 安全核签中心
            </h1>
            <p className="text-xs text-slate-500 mt-0.5">
              企业级多租户 Human-in-the-Loop 审批流与 APM 财务算力监控控制台
            </p>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          {/* Merchant Selector */}
          <div className="flex items-center space-x-1 bg-slate-900 border border-slate-800 p-1 rounded-xl">
            {['ecommerce', 'nike', 'adidas', 'puma'].map((m) => (
              <button
                key={m}
                onClick={() => setSelectedMerchant(m)}
                className={`px-3 py-1.5 rounded-lg text-xs font-semibold uppercase tracking-wider transition ${
                  selectedMerchant === m
                    ? 'bg-indigo-600 text-white shadow-md'
                    : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/40'
                }`}
              >
                {m}
              </button>
            ))}
          </div>

          <button
            onClick={fetchDashboardData}
            className="h-9 w-9 flex items-center justify-center rounded-xl bg-slate-900 border border-slate-800 text-slate-400 hover:text-slate-200 transition"
          >
            <RefreshCw className={`h-4 w-4 ${isRefreshing ? 'animate-spin text-indigo-400' : ''}`} />
          </button>
        </div>
      </header>

      <main className="p-8 max-w-7xl mx-auto space-y-8">
        {/* 📊 SaaS Telemetry BI Metrics Cards */}
        <section className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-4">
          <div className="bg-slate-900/60 border border-slate-800/80 rounded-2xl p-5 space-y-2 relative overflow-hidden group">
            <div className="absolute right-4 top-4 opacity-5 group-hover:opacity-10 transition">
              <DollarSign className="h-14 w-14 text-white" />
            </div>
            <span className="text-[10px] font-bold text-slate-500 uppercase tracking-widest block font-mono">
              TOTAL ACCRUED COST
            </span>
            <div className="flex items-baseline gap-1">
              <span className="text-2xl font-bold font-mono text-emerald-400">
                ${summary.totalCostUsd.toFixed(5)}
              </span>
              <span className="text-[10px] text-slate-500 font-mono">USD</span>
            </div>
            <span className="text-[10px] text-slate-400 block mt-1">
              商户算力总损耗 (Gemini 3.5)
            </span>
          </div>

          <div className="bg-slate-900/60 border border-slate-800/80 rounded-2xl p-5 space-y-2 relative overflow-hidden group">
            <div className="absolute right-4 top-4 opacity-5 group-hover:opacity-10 transition">
              <Layers className="h-14 w-14 text-white" />
            </div>
            <span className="text-[10px] font-bold text-slate-500 uppercase tracking-widest block font-mono">
              TOTAL CONVERSATIONS
            </span>
            <div className="text-2xl font-bold font-mono text-indigo-400">
              {summary.totalSessions}
            </div>
            <span className="text-[10px] text-slate-400 block mt-1">
              会话线程物理总数
            </span>
          </div>

          <div className="bg-slate-900/60 border border-slate-800/80 rounded-2xl p-5 space-y-2 relative overflow-hidden group">
            <div className="absolute right-4 top-4 opacity-5 group-hover:opacity-10 transition">
              <Clock className="h-14 w-14 text-white" />
            </div>
            <span className="text-[10px] font-bold text-slate-500 uppercase tracking-widest block font-mono">
              AVERAGE LATENCY
            </span>
            <div className="flex items-baseline gap-1">
              <span className="text-2xl font-bold font-mono text-amber-400">
                {summary.avgLatencyMs}
              </span>
              <span className="text-[10px] text-slate-500 font-mono">MS</span>
            </div>
            <span className="text-[10px] text-slate-400 block mt-1">
              单次对话全图决策平均耗时
            </span>
          </div>

          <div className="bg-slate-900/60 border border-slate-800/80 rounded-2xl p-5 space-y-2 relative overflow-hidden group">
            <div className="absolute right-4 top-4 opacity-5 group-hover:opacity-10 transition">
              <Cpu className="h-14 w-14 text-white" />
            </div>
            <span className="text-[10px] font-bold text-slate-500 uppercase tracking-widest block font-mono">
              AVERAGE TOKENS
            </span>
            <div className="text-2xl font-bold font-mono text-slate-200">
              {summary.avgTokens}
            </div>
            <span className="text-[10px] text-slate-400 block mt-1">
              单会话大模型 Token 平均损耗
            </span>
          </div>

          <div className="bg-slate-900/60 border border-slate-800/80 rounded-2xl p-5 space-y-2 relative overflow-hidden group col-span-1 sm:col-span-2 lg:col-span-1">
            <div className="absolute right-4 top-4 opacity-5 group-hover:opacity-10 transition">
              <TrendingUp className="h-14 w-14 text-white" />
            </div>
            <span className="text-[10px] font-bold text-slate-500 uppercase tracking-widest block font-mono">
              AUTOPILOT SUCCESS
            </span>
            <div className="flex items-baseline gap-1">
              <span className="text-2xl font-bold font-mono text-emerald-400">
                {summary.autopilotRate}%
              </span>
            </div>
            <span className="text-[10px] text-slate-400 block mt-1">
              AI 自主解决率 / 免审批放行比
            </span>
          </div>
        </section>

        {/* 🛡️ Section 1: Active Pending Approvals Queue */}
        <section className="space-y-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center space-x-2">
              <ShieldAlert className="h-5 w-5 text-amber-500 animate-pulse" />
              <h2 className="text-sm font-bold tracking-wider uppercase text-slate-300">
                🛡️ 安全红线拦截：待人工核准工单 ({pendingApprovals.length})
              </h2>
            </div>
            <span className="text-[10px] font-mono text-slate-500 uppercase">
              Real-time approval dispatch queue
            </span>
          </div>

          {pendingApprovals.length === 0 ? (
            <div className="bg-slate-900/30 border border-slate-850 rounded-2xl py-14 text-center space-y-3">
              <CheckCircle2 className="h-10 w-10 text-emerald-500/80 mx-auto" />
              <p className="text-xs text-slate-400">
                当前大盘一片绿灯！所有待审批工单已全部核签完成。
              </p>
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
              {pendingApprovals.map((approval) => {
                const args = approval.actionPayload?.args || {};
                const isSubmitting = submittingActionId === approval.id;

                return (
                  <div
                    key={approval.id}
                    className="bg-slate-900 border border-amber-500/30 hover:border-amber-500/50 rounded-2xl overflow-hidden shadow-xl transition-all"
                  >
                    {/* Header */}
                    <div className="bg-amber-500/10 px-5 py-4 border-b border-amber-500/20 flex justify-between items-center">
                      <div className="flex items-center space-x-2">
                        <Activity className="h-4 w-4 text-amber-400 animate-spin-slow" />
                        <span className="text-xs font-bold text-amber-300 uppercase tracking-wider font-mono">
                          {approval.actionType}
                        </span>
                      </div>
                      <span className="text-[9px] font-mono text-amber-400 bg-amber-500/15 px-2 py-0.5 rounded">
                        Waiting Approval
                      </span>
                    </div>

                    {/* Content */}
                    <div className="p-5 space-y-4">
                      {/* Metadatas */}
                      <div className="space-y-1 text-xs">
                        <div className="flex justify-between">
                          <span className="text-slate-500">工单 ID:</span>
                          <span className="font-mono text-slate-300">{approval.id.substring(0, 8)}...</span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-slate-500">Thread ID:</span>
                          <span className="font-mono text-slate-300 truncate max-w-[150px]">
                            {approval.threadId}
                          </span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-slate-500">截止日期:</span>
                          <span className="font-mono text-amber-400/80">
                            {new Date(approval.deadline).toLocaleTimeString([], {
                              hour: '2-digit',
                              minute: '2-digit',
                            })}
                          </span>
                        </div>
                      </div>

                      {/* Payload Visualization */}
                      <div className="bg-slate-950 border border-slate-850 rounded-xl p-3.5 space-y-2.5">
                        <span className="text-[9px] font-bold text-slate-500 uppercase tracking-widest block font-mono">
                          ACTION PAYLOAD DETAILS
                        </span>
                        <div className="text-xs font-mono text-slate-300 space-y-1.5 overflow-x-auto">
                          {Object.entries(args).map(([k, v]) => (
                            <div key={k} className="flex gap-2">
                              <span className="text-slate-500">{k}:</span>
                              <span className="text-indigo-300">{String(v)}</span>
                            </div>
                          ))}
                        </div>
                      </div>

                      {/* Actions Form */}
                      <div className="space-y-2">
                        <input
                          type="text"
                          value={rejectionReasons[approval.id] || ''}
                          onChange={(e) =>
                            setRejectionReasons((prev) => ({ ...prev, [approval.id]: e.target.value }))
                          }
                          placeholder="驳回请在此输入拒绝理由..."
                          className="w-full bg-slate-950 border border-slate-850 rounded-xl px-3 py-2 text-xs text-slate-100 placeholder-slate-600 focus:outline-none focus:border-indigo-500"
                        />

                        <div className="flex gap-2 pt-1">
                          <button
                            onClick={() => handleApprovalAction(approval.id, 'approve')}
                            disabled={isSubmitting}
                            className="flex-1 h-8 text-[11px] font-bold bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-white rounded-xl transition flex items-center justify-center gap-1.5"
                          >
                            {isSubmitting ? (
                              <Loader2 className="h-3.5 w-3.5 animate-spin" />
                            ) : (
                              <>
                                <CheckCircle2 className="h-3.5 w-3.5" />
                                <span>核准通过</span>
                              </>
                            )}
                          </button>
                          <button
                            onClick={() => handleApprovalAction(approval.id, 'reject')}
                            disabled={isSubmitting}
                            className="flex-1 h-8 text-[11px] font-bold bg-rose-600 hover:bg-rose-500 disabled:opacity-50 text-white rounded-xl transition flex items-center justify-center gap-1.5"
                          >
                            {isSubmitting ? (
                              <Loader2 className="h-3.5 w-3.5 animate-spin" />
                            ) : (
                              <>
                                <XCircle className="h-3.5 w-3.5" />
                                <span>驳回申请</span>
                              </>
                            )}
                          </button>
                        </div>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </section>

        {/* 📁 Section 2: Historical Audited Records */}
        <section className="space-y-4">
          <div className="flex items-center space-x-2">
            <CheckCircle2 className="h-5 w-5 text-slate-500" />
            <h2 className="text-sm font-bold tracking-wider uppercase text-slate-400">
              📁 历史核签审计归档记录 ({auditedApprovals.length})
            </h2>
          </div>

          <div className="bg-slate-900 border border-slate-800 rounded-2xl overflow-hidden shadow-xl">
            <div className="overflow-x-auto">
              <table className="w-full text-left border-collapse text-xs">
                <thead>
                  <tr className="border-b border-slate-850 bg-slate-950/40 text-slate-500 font-mono font-bold tracking-wider">
                    <th className="p-4">工单 ID</th>
                    <th className="p-4">业务场景</th>
                    <th className="p-4">操作类型</th>
                    <th className="p-4">数据详情</th>
                    <th className="p-4">完成状态</th>
                    <th className="p-4">审计时间</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-850">
                  {auditedApprovals.length === 0 ? (
                    <tr>
                      <td colSpan={6} className="p-8 text-center text-slate-500 font-mono">
                        No historical audit records found.
                      </td>
                    </tr>
                  ) : (
                    auditedApprovals.map((app) => {
                      const args = app.actionPayload?.args || {};
                      const comment = app.actionPayload?.rejectionReason || '';

                      return (
                        <tr key={app.id} className="hover:bg-slate-950/20 transition-colors">
                          <td className="p-4 font-mono text-slate-300">
                            {app.id.substring(0, 8)}...
                          </td>
                          <td className="p-4 font-mono">
                            <span className="px-2 py-0.5 rounded bg-slate-950 border border-slate-850 text-slate-400 font-semibold uppercase tracking-wider text-[9px]">
                              {app.threadId.startsWith('test_suite') ? 'test_suite' : 'ecommerce'}
                            </span>
                          </td>
                          <td className="p-4 font-bold text-slate-300">{app.actionType}</td>
                          <td className="p-4 max-w-[250px]">
                            <div className="font-mono text-[10px] text-slate-400 bg-slate-950/40 border border-slate-850/60 p-2 rounded-lg space-y-1">
                              {Object.entries(args).map(([k, v]) => (
                                <div key={k} className="truncate">
                                  {k}: <span className="text-slate-200">{String(v)}</span>
                                </div>
                              ))}
                              {comment && (
                                <div className="border-t border-slate-850/60 pt-1 text-rose-400 font-sans truncate">
                                  驳回理由: {comment}
                                </div>
                              )}
                            </div>
                          </td>
                          <td className="p-4">
                            <span
                              className={`px-2.5 py-0.5 rounded-full font-bold text-[9px] uppercase tracking-wider inline-block ${
                                app.status === 'approved'
                                  ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/15'
                                  : app.status === 'rejected'
                                    ? 'bg-rose-500/10 text-rose-400 border border-rose-500/15'
                                    : 'bg-slate-500/10 text-slate-400 border border-slate-800'
                              }`}
                            >
                              {app.status}
                            </span>
                          </td>
                          <td className="p-4 font-mono text-slate-500">
                            {new Date(app.createdAt).toLocaleString([], {
                              month: '2-digit',
                              day: '2-digit',
                              hour: '2-digit',
                              minute: '2-digit',
                            })}
                          </td>
                        </tr>
                      );
                    })
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </section>
      </main>
    </div>
  );
}
