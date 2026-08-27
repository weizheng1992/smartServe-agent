'use client';

import type React from 'react';
import type { RefundConfirmationData } from 'types';
import { Clock, ShieldCheck } from '../../icons';

export interface RefundConfirmationCardProps {
  data: RefundConfirmationData;
  onConfirm?: () => void;
}

function formatAmount(val: unknown): string {
  if (typeof val === 'number') return val.toFixed(2);
  if (typeof val === 'string') {
    const num = Number.parseFloat(val.replace(/[^0-9.-]/g, ''));
    return Number.isNaN(num) ? '0.00' : num.toFixed(2);
  }
  return '0.00';
}

export const RefundConfirmationCard: React.FC<RefundConfirmationCardProps> = ({ data, onConfirm }) => {
  const isApproved = data.status === 'approved';
  const isPending = data.status === 'pending_confirmation';

  return (
    <div className="my-2 max-w-md overflow-hidden rounded-xl border border-rose-900/40 bg-gradient-to-b from-rose-950/30 to-slate-900/90 p-4 text-slate-100 shadow-xl backdrop-blur-md">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-rose-900/30 pb-3">
        <div className="flex items-center gap-2">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-rose-500/10 text-rose-400">
            <ShieldCheck className="h-4 w-4" />
          </div>
          <div>
            <div className="text-xs font-semibold text-rose-300">退款核签与赔付凭证</div>
            <div className="font-mono text-sm font-bold text-slate-200">{data.orderId}</div>
          </div>
        </div>
        <span
          className={`inline-flex items-center rounded-full px-2.5 py-1 text-xs font-medium ${
            isApproved
              ? 'bg-emerald-500/10 text-emerald-400 ring-1 ring-inset ring-emerald-500/20'
              : isPending
                ? 'bg-amber-500/10 text-amber-400 ring-1 ring-inset ring-amber-500/20'
                : 'bg-rose-500/10 text-rose-400 ring-1 ring-inset ring-rose-500/20'
          }`}
        >
          {isApproved ? '已放行退款' : isPending ? '待人工核签' : '已受理申请'}
        </span>
      </div>

      {/* Info Body */}
      <div className="my-3 space-y-2 text-xs">
        <div className="flex justify-between text-slate-300">
          <span className="text-slate-400">核定退款金额:</span>
          <span className="font-mono text-base font-bold text-rose-400">
            {data.currency === 'USD' ? '$' : '¥'}
            {formatAmount(data.refundAmount)}
          </span>
        </div>
        <div className="flex justify-between text-slate-300">
          <span className="text-slate-400">退款原因:</span>
          <span className="text-slate-200">{data.refundReason}</span>
        </div>
        <div className="flex justify-between text-slate-300">
          <span className="text-slate-400">返还方式:</span>
          <span className="text-slate-200">{data.refundMethod}</span>
        </div>
      </div>

      {isPending && (
        <div className="mt-3 flex items-center gap-2 rounded-lg bg-amber-500/10 p-2.5 text-xs text-amber-300 border border-amber-500/20">
          <Clock className="h-4 w-4 shrink-0" />
          <span>当前退款触发商户高额风控线，已自动生成工单提交至人工客服复核。</span>
        </div>
      )}
    </div>
  );
};
