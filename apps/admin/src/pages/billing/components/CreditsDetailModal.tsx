import { useEffect, useState } from 'react';
import { Button, Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from 'ui';
import { billingApi, type CreditsDetail } from '../../../lib/api';
import { describeCreditReason, formatCreditDelta, formatCreditTime } from '../credits';
import type { TenantBillingRecord } from '../types';

export interface CreditsDetailModalProps {
  isOpen: boolean;
  onClose: () => void;
  record: TenantBillingRecord | null;
}

/** 积分流水弹窗:余额 + 最近流水(服务端新→旧返回,原序呈现)。
 *  balance null = 未开通,诚实呈现严禁编 0;加载失败诚实文案可重试。 */
export function CreditsDetailModal({ isOpen, onClose, record }: CreditsDetailModalProps) {
  const [detail, setDetail] = useState<CreditsDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const businessId = record?.businessId || '';

  useEffect(() => {
    if (!isOpen || !businessId) return;
    let alive = true;
    setLoading(true);
    setError('');
    setDetail(null);
    (async () => {
      try {
        const res = await billingApi.getCredits(businessId);
        if (!alive) return;
        if (!res.success || !res.data) {
          setError(res.error || '积分流水加载失败');
        } else {
          setDetail(res.data);
        }
      } catch (err) {
        if (alive) setError(err instanceof Error ? err.message : '网络通信异常,请检查后端网关是否已启动');
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => {
      alive = false;
    };
  }, [isOpen, businessId]);

  return (
    <Dialog open={isOpen} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="z-50 w-full max-w-lg gap-0 overflow-hidden rounded-2xl border border-slate-200 bg-white p-0 shadow-xl">
        <DialogHeader className="space-y-0 border-b border-slate-100 bg-slate-50/60 px-6 py-4 text-left">
          <DialogTitle className="text-base font-semibold text-slate-900">
            积分流水: {record?.tenantName || ''}
          </DialogTitle>
          <DialogDescription className="mt-0.5 text-xs text-slate-500">
            商户共享积分池台账(1 次问询 = 1 积分;充值 / 核减由平台管理员操作)
          </DialogDescription>
        </DialogHeader>

        <div className="max-h-[70vh] overflow-y-auto px-6 py-4 text-sm">
          {loading && <div className="py-6 text-center text-xs text-slate-400">加载中…</div>}
          {!loading && error && (
            <div className="space-y-2 py-6 text-center">
              <div className="text-xs text-rose-600">{error}</div>
              <Button type="button" variant="outline" size="sm" onClick={() => onClose()} className="text-xs">
                关闭
              </Button>
            </div>
          )}
          {!loading && !error && detail && (
            <>
              <div className="mb-4 flex items-baseline justify-between rounded-xl bg-slate-50 px-4 py-3">
                <span className="text-xs text-slate-500">当前余额</span>
                {detail.balance === null || detail.balance === undefined ? (
                  <span className="text-sm font-semibold text-slate-400">未开通</span>
                ) : (
                  <span className="text-2xl font-bold tabular-nums text-slate-900">
                    {detail.balance.toLocaleString()}
                    <span className="ml-1 text-xs font-normal text-slate-400">积分</span>
                  </span>
                )}
              </div>

              {detail.transactions.length === 0 ? (
                <div className="py-6 text-center text-xs text-slate-400">暂无流水记录</div>
              ) : (
                <ul className="divide-y divide-slate-100">
                  {detail.transactions.map((t) => (
                    <li key={t.id} className="flex items-start justify-between gap-3 py-2.5">
                      <div className="min-w-0">
                        <div className="flex items-center gap-2">
                          <span
                            className={`font-mono text-xs font-bold ${
                              t.delta > 0 ? 'text-emerald-600' : 'text-rose-600'
                            }`}
                          >
                            {formatCreditDelta(t.delta)}
                          </span>
                          <span className="truncate text-xs text-slate-700">{describeCreditReason(t.reason)}</span>
                        </div>
                        <div className="mt-0.5 truncate text-[11px] text-slate-400">
                          {t.operator ? `操作人 ${t.operator}` : ''}
                          {t.operator && t.refJobId ? ' · ' : ''}
                          {t.refJobId ? `关联回合 ${t.refJobId}` : ''}
                          {!t.operator && !t.refJobId ? '—' : ''}
                        </div>
                      </div>
                      <span className="shrink-0 text-[11px] tabular-nums text-slate-400">
                        {formatCreditTime(t.createdAt)}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
