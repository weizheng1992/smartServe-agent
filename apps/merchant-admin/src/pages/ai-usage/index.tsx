import { BarChart } from '@/components/BarChart';
import { CreditsCard } from '@/components/credits-card';
import { LineChart } from '@/components/LineChart';
import {
  DenseTable,
  DenseTableBody,
  DenseTableCell,
  DenseTableHead,
  DenseTableHeader,
  DenseTableRow,
} from '@/components/dense-table';
import { type AiUsageCall, type AiUsageSummary, type AiUsageTurn, api, errMsgOf } from '@/lib/api';
import { useCallback, useEffect, useState } from 'react';
import { Button } from 'ui';

// AI 用量页(docs/ai-usage-panel.md P0-3):轮(session_metrics 每轮一行)为面、
// LLM 调用(llm_call_logs 按 jobId)为下钻。诚实律同 CreditsCard —— 自然月窗
// 口由服务端单点计算;无美元(成本是平台内部数据);轮未决路径/无 job 关联的
// 历史轮如实呈现,严禁编数。

/** turn_path 闭集中文标签(与引擎 turn_path_for_route 同源,前端仅呈现)。
 *  unknown = NULL:升级前历史行与三个降级臂,统一「未记录」如实呈现。 */
const TURN_PATH_LABEL: Record<string, string> = {
  greeting: '极速问候',
  semantic_cache: '同问缓存命中',
  duplicate_bypass: '重复提问拦截',
  rag_direct: '咨询直答快轨',
  clarify: '澄清反问',
  bypass_other: '确定性旁路',
  deep_path: '全管线',
  unknown: '未记录',
};

const turnPathLabel = (p: string | null): string => (p ? (TURN_PATH_LABEL[p] ?? p) : '未记录');

function fmtInt(n: number): string {
  return n.toLocaleString('zh-CN');
}

function fmtPct(rate: number): string {
  return `${(rate * 100).toFixed(1)}%`;
}

function fmtTime(iso: string | null): string {
  if (!iso) return '—';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? '—' : d.toLocaleString('zh-CN', { hour12: false });
}

function KpiCard({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="rounded-2xl border border-zinc-200 bg-white p-4" aria-label={label}>
      <div className="text-[11px] text-zinc-400">{label}</div>
      <div className="mt-1 text-xl font-semibold tabular-nums text-zinc-900">{value}</div>
      {sub ? <div className="mt-0.5 text-[11px] text-zinc-400">{sub}</div> : null}
    </div>
  );
}

export default function AiUsagePage() {
  const [summary, setSummary] = useState<AiUsageSummary | null>(null);
  const [phase, setPhase] = useState<'loading' | 'ready' | 'error'>('loading');
  const [msg, setMsg] = useState('');
  const [turns, setTurns] = useState<AiUsageTurn[]>([]);
  const [turnsPhase, setTurnsPhase] = useState<'loading' | 'ready' | 'error'>('loading');
  const [selectedJob, setSelectedJob] = useState<string | null>(null);
  const [calls, setCalls] = useState<AiUsageCall[] | null>(null);
  const [callsLoading, setCallsLoading] = useState(false);
  const [callsMsg, setCallsMsg] = useState('');

  const load = useCallback(async () => {
    setPhase('loading');
    setMsg('');
    try {
      const body = await api.aiUsage.summary();
      if (!body.success || !body.data) {
        setPhase('error');
        setMsg(errMsgOf(body, 'AI 用量加载失败'));
        return;
      }
      setSummary(body.data);
      setPhase('ready');
    } catch (err) {
      setPhase('error');
      setMsg(err instanceof Error ? err.message : '网络异常,请确认网关(4000)是否存活');
    }
  }, []);

  const loadTurns = useCallback(async () => {
    setTurnsPhase('loading');
    try {
      const body = await api.aiUsage.turns();
      if (!body.success || !body.data) {
        setTurnsPhase('error');
        setMsg(errMsgOf(body, '轮列表加载失败'));
        return;
      }
      setTurns(body.data.turns || []);
      setTurnsPhase('ready');
    } catch (err) {
      setTurnsPhase('error');
      setMsg(err instanceof Error ? err.message : '网络异常');
    }
  }, []);

  useEffect(() => {
    void load();
    void loadTurns();
  }, [load, loadTurns]);

  const openCalls = useCallback(async (jobId: string) => {
    setSelectedJob(jobId);
    setCallsLoading(true);
    setCallsMsg('');
    try {
      const body = await api.aiUsage.calls(jobId);
      if (!body.success || !body.data) {
        setCalls(null);
        setCallsMsg(errMsgOf(body, '调用明细加载失败'));
        return;
      }
      setCalls(body.data.calls);
    } catch (err) {
      setCalls(null);
      setCallsMsg(err instanceof Error ? err.message : '网络异常');
    } finally {
      setCallsLoading(false);
    }
  }, []);

  if (phase === 'loading') {
    return <div className="p-6 text-sm text-zinc-500">加载中…</div>;
  }
  if (phase === 'error' || !summary) {
    return (
      <div className="p-6">
        <div className="rounded-2xl border border-zinc-200 bg-white p-6 text-sm text-zinc-600">
          {msg || 'AI 用量加载失败'}
        </div>
        <Button type="button" variant="outline" className="mt-3 cursor-pointer" onClick={() => void load()}>
          重试
        </Button>
      </div>
    );
  }

  const { quota, turns: turnStats, byDay, byPath, calls: callStats } = summary;

  return (
    <div className="space-y-4 p-6">
      <div className="flex items-center justify-between">
        <div>
          <div className="text-base font-semibold text-zinc-900">AI 用量</div>
          <div className="mt-0.5 text-[11px] text-zinc-400">
            自然月窗口 · 轮 = 一次问询到一次回复 · 零 LLM 命中 = 问候/缓存/重复拦截直接复放
          </div>
        </div>
        <Button type="button" variant="outline" className="cursor-pointer" onClick={() => void load()}>
          刷新
        </Button>
      </div>

      <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
        <KpiCard
          label="本月 Token"
          value={fmtInt(quota.usedTokens)}
          sub={quota.monthlyLimitTokens ? `限额 ${fmtInt(quota.monthlyLimitTokens)} · 已用 ${quota.usageRate !== null ? fmtPct(quota.usageRate) : '—'}` : '未配置月度限额'}
        />
        <KpiCard
          label="本月轮数"
          value={fmtInt(turnStats.total)}
          sub={`平均轮延迟 ${(turnStats.avgLatencyMs / 1000).toFixed(1)} 秒`}
        />
        <KpiCard
          label="零 LLM 命中率"
          value={fmtPct(turnStats.zeroLlmRate)}
          sub="问候 / 缓存 / 重复拦截占比 · 0 次模型调用"
        />
        <KpiCard
          label="快轨占比"
          value={fmtPct(turnStats.fastPathRate)}
          sub={`含咨询直答 · 全管线调用 ${fmtInt(callStats.total)} 次 / ${fmtInt(callStats.totalTokens)} tok`}
        />
      </div>

      <div className="grid grid-cols-1 gap-3 xl:grid-cols-2">
        <div className="rounded-2xl border border-zinc-200 bg-white p-4">
          <div className="text-sm font-medium">Token 按天趋势</div>
          <LineChart points={byDay.map((d) => ({ label: d.day.slice(5), value: d.tokens }))} unit=" tok" />
        </div>
        <div className="rounded-2xl border border-zinc-200 bg-white p-4">
          <div className="text-sm font-medium">轮路径分布</div>
          <BarChart points={byPath.map((p) => ({ label: turnPathLabel(p.path), value: p.turns }))} unit=" 轮" />
        </div>
      </div>

      <div className="grid grid-cols-1 gap-3 xl:grid-cols-2">
        <CreditsCard />
        <div className="rounded-2xl border border-zinc-200 bg-white p-4">
          <div className="text-sm font-medium">调用口径说明</div>
          <ul className="mt-2 space-y-1.5 text-xs text-zinc-500">
            <li>· 配额口径:session_metrics(与计费闸同源);调用口径:llm_call_logs 归因行。</li>
            {summary.notes.map((n) => (
              <li key={n}>· {n}</li>
            ))}
            <li>· 本页不展示美元成本 —— 真实单价属平台内部数据,商户侧以 token 与积分计。</li>
          </ul>
        </div>
      </div>

      <div className="rounded-2xl border border-zinc-200 bg-white p-4">
        <div className="flex items-center justify-between">
          <div className="text-sm font-medium">最近轮次(新 → 旧,点行下钻调用明细)</div>
          <Button type="button" variant="ghost" className="cursor-pointer text-xs" onClick={() => void loadTurns()}>
            刷新列表
          </Button>
        </div>
        {turnsPhase === 'loading' ? (
          <div className="p-3 text-xs text-zinc-400">加载中…</div>
        ) : turnsPhase === 'error' ? (
          <div className="p-3 text-xs text-red-600">{msg}</div>
        ) : turns.length === 0 ? (
          <div className="p-3 text-xs text-zinc-400">本月暂无轮记录(诚实空)</div>
        ) : (
          <DenseTable className="mt-2 text-left text-xs">
            <DenseTableHeader>
              <DenseTableRow className="hover:bg-transparent">
                <DenseTableHead className="py-1 pr-3 text-xs">时间</DenseTableHead>
                <DenseTableHead className="py-1 pr-3 text-xs">路径</DenseTableHead>
                <DenseTableHead className="py-1 pr-3 text-xs">Token</DenseTableHead>
                <DenseTableHead className="py-1 pr-3 text-xs">耗时</DenseTableHead>
                <DenseTableHead className="py-1 pr-3 text-xs">终态</DenseTableHead>
                <DenseTableHead className="py-1 text-xs">下钻</DenseTableHead>
              </DenseTableRow>
            </DenseTableHeader>
            <DenseTableBody>
              {turns.map((t) => (
                <DenseTableRow
                  key={t.jobId ?? `${t.threadId}:${t.createdAt ?? ''}`}
                  className={`border-t border-zinc-100 ${selectedJob && selectedJob === t.jobId ? 'bg-zinc-50' : ''}`}
                >
                  <DenseTableCell className="py-1 pr-3 text-xs tabular-nums">{fmtTime(t.createdAt)}</DenseTableCell>
                  <DenseTableCell className="py-1 pr-3 text-xs">{turnPathLabel(t.turnPath)}</DenseTableCell>
                  <DenseTableCell className="py-1 pr-3 text-xs tabular-nums">{fmtInt(t.totalTokens)}</DenseTableCell>
                  <DenseTableCell className="py-1 pr-3 text-xs tabular-nums">
                    {t.latencyMs >= 1000 ? `${(t.latencyMs / 1000).toFixed(1)}s` : `${t.latencyMs}ms`}
                  </DenseTableCell>
                  <DenseTableCell className="py-1 pr-3 text-xs text-zinc-500">{t.resolutionStatus}</DenseTableCell>
                  <DenseTableCell className="py-1 text-xs">
                    {t.jobId ? (
                      <Button
                        type="button"
                        variant="ghost"
                        className="h-6 cursor-pointer px-2 text-xs"
                        onClick={() => void openCalls(t.jobId as string)}
                      >
                        调用明细
                      </Button>
                    ) : (
                      <span className="text-zinc-400">无关联(历史轮)</span>
                    )}
                  </DenseTableCell>
                </DenseTableRow>
              ))}
            </DenseTableBody>
          </DenseTable>
        )}

        {selectedJob ? (
          <div className="mt-3 rounded-xl border border-zinc-100 bg-zinc-50 p-3" aria-label="调用明细">
            <div className="text-xs font-medium text-zinc-600">
              轮 {selectedJob} 的 LLM 调用明细
            </div>
            {callsLoading ? (
              <div className="p-2 text-xs text-zinc-400">加载中…</div>
            ) : callsMsg ? (
              <div className="p-2 text-xs text-red-600">{callsMsg}</div>
            ) : calls && calls.length > 0 ? (
              <DenseTable className="mt-2 text-left text-xs">
                <DenseTableHeader>
                  <DenseTableRow className="hover:bg-transparent">
                    <DenseTableHead className="py-1 pr-3 text-xs">节点</DenseTableHead>
                    <DenseTableHead className="py-1 pr-3 text-xs">模型</DenseTableHead>
                    <DenseTableHead className="py-1 pr-3 text-xs">输入 tok</DenseTableHead>
                    <DenseTableHead className="py-1 pr-3 text-xs">输出 tok</DenseTableHead>
                    <DenseTableHead className="py-1 pr-3 text-xs">耗时</DenseTableHead>
                  </DenseTableRow>
                </DenseTableHeader>
                <DenseTableBody>
                  {calls.map((c, i) => (
                    <DenseTableRow key={`${c.node}:${i}`} className="border-t border-zinc-100">
                      <DenseTableCell className="py-1 pr-3 text-xs">{c.node}</DenseTableCell>
                      <DenseTableCell className="py-1 pr-3 text-xs text-zinc-500">{c.model}</DenseTableCell>
                      <DenseTableCell className="py-1 pr-3 text-xs tabular-nums">{fmtInt(c.tokensIn)}</DenseTableCell>
                      <DenseTableCell className="py-1 pr-3 text-xs tabular-nums">{fmtInt(c.tokensOut)}</DenseTableCell>
                      <DenseTableCell className="py-1 text-xs tabular-nums">
                        {c.latencyMs >= 1000 ? `${(c.latencyMs / 1000).toFixed(1)}s` : `${c.latencyMs}ms`}
                      </DenseTableCell>
                    </DenseTableRow>
                  ))}
                </DenseTableBody>
              </DenseTable>
            ) : (
              <div className="p-2 text-xs text-zinc-400">本轮 0 次 LLM 调用(零 LLM 快轨直接复放,诚实空)</div>
            )}
          </div>
        ) : null}
      </div>
    </div>
  );
}
