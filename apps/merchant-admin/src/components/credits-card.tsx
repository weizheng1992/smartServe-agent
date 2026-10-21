import { type CreditsDetail, api } from '@/lib/api';
import { creditReasonMeta } from '@/lib/format';
import { useCallback, useEffect, useState } from 'react';
import { Button } from 'ui';

// 服务额度(积分)只读卡(2026-10-21 用量配额闸,spec §5 merchant-admin 面)。
// 嵌数据看板页(常驻仪表盘)—— 不加菜单(RBAC 菜单树在服务端种子,不动)。
// 诚实律:balance null = 未开通,严禁编 0;加载失败诚实文案 + 重试,不假绿。

const MAX_ROWS = 10;

function formatDelta(delta: number): string {
  return delta > 0 ? `+${delta}` : String(delta);
}

function formatTime(iso: string | null): string {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '—';
  return d.toLocaleString('zh-CN', { hour12: false });
}

export function CreditsCard() {
  const [detail, setDetail] = useState<CreditsDetail | null>(null);
  const [phase, setPhase] = useState<'loading' | 'ready' | 'error'>('loading');
  const [errMsg, setErrMsg] = useState('');

  const load = useCallback(async () => {
    setPhase('loading');
    setErrMsg('');
    try {
      const body = await api.credits.get();
      if (!body.success || !body.data) {
        // 业务/HTTP 错误体原样呈现(transport 收口语义),不吞不编
        setPhase('error');
        setErrMsg(body.error || '服务额度加载失败');
        return;
      }
      setDetail(body.data);
      setPhase('ready');
    } catch (err) {
      setPhase('error');
      setErrMsg(err instanceof Error ? err.message : '网络异常,请确认网关(4000)是否存活');
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const transactions = detail ? detail.transactions.slice(0, MAX_ROWS) : [];

  return (
    <div className="rounded-2xl border border-zinc-200 bg-white p-4" aria-label="服务额度(积分)">
      <div className="flex items-center justify-between">
        <div className="text-sm font-medium">服务额度(积分)</div>
        <span className="text-[11px] text-zinc-400">1 次问询 = 1 积分 · 只读</span>
      </div>

      <div className="mt-2 flex items-baseline gap-2">
        {phase === 'loading' ? (
          <span className="text-xs text-zinc-400">加载中…</span>
        ) : phase === 'error' ? (
          <>
            <span className="text-xs text-zinc-500">{errMsg}</span>
            <Button type="button" variant="outline" size="sm" className="h-auto px-2 py-0.5 text-[11px]" onClick={() => void load()}>
              重试
            </Button>
          </>
        ) : detail?.balance === null || detail?.balance === undefined ? (
          // 未开通:服务端明示 null 才算数,诚实呈现,严禁回落 0
          <span className="text-sm font-semibold text-zinc-400">未开通</span>
        ) : (
          <>
            <span className="text-2xl font-bold tabular-nums text-zinc-900">{detail.balance.toLocaleString()}</span>
            <span className="text-xs text-zinc-400">积分</span>
          </>
        )}
      </div>

      {phase === 'ready' && (
        <div className="mt-3 border-t border-zinc-100 pt-2">
          <div className="mb-1 text-[11px] text-zinc-400">最近 {MAX_ROWS} 条流水</div>
          {transactions.length === 0 ? (
            <div className="py-3 text-xs text-zinc-400">暂无流水记录</div>
          ) : (
            <ul className="divide-y divide-zinc-50">
              {transactions.map((t) => (
                <li key={t.id} className="flex items-center justify-between gap-3 py-1.5">
                  <div className="flex min-w-0 items-center gap-2">
                    <span
                      className={`font-mono text-xs font-bold tabular-nums ${
                        t.delta > 0 ? 'text-emerald-600' : 'text-rose-600'
                      }`}
                    >
                      {formatDelta(t.delta)}
                    </span>
                    <span className="truncate text-xs text-zinc-700">{creditReasonMeta(t.reason)}</span>
                  </div>
                  <div className="shrink-0 text-right">
                    <div className="text-[11px] tabular-nums text-zinc-400">{formatTime(t.createdAt)}</div>
                    {t.operator ? <div className="text-[10px] text-zinc-300">{t.operator}</div> : null}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
