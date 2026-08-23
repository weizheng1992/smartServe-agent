import type React from 'react';
import type { PendingApprovalRecord } from 'types';
import { Shield } from 'ui';

export type AuditFilterType = 'ALL' | 'WAITING' | 'APPROVED' | 'REJECTED' | 'EXPIRED';

interface ApprovalFilterHeaderProps {
  allApprovals: PendingApprovalRecord[];
  auditFilter: AuditFilterType;
  setAuditFilter: (filter: AuditFilterType) => void;
  setSelectedApprovalId: (id: string | null) => void;
}

export function ApprovalFilterHeader({
  allApprovals,
  auditFilter,
  setAuditFilter,
  setSelectedApprovalId,
}: ApprovalFilterHeaderProps) {
  const filters: AuditFilterType[] = ['ALL', 'WAITING', 'APPROVED', 'REJECTED', 'EXPIRED'];
  const labelMap: Record<AuditFilterType, string> = {
    ALL: '全部',
    WAITING: '待审批',
    APPROVED: '已核准',
    REJECTED: '已驳回',
    EXPIRED: '已超时',
  };

  return (
    <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 pb-6 border-b border-slate-800 shrink-0">
      <div className="space-y-1">
        <div className="flex items-center gap-2">
          <Shield className="h-5 w-5 text-indigo-400" />
          <h1 className="text-lg font-bold tracking-tight text-slate-100 uppercase">
            smartServe 客服安全审查与核签大盘
          </h1>
        </div>
        <p className="text-xs text-slate-500 font-medium">全渠道多租户 Human-in-the-Loop 安全拦截工单审计平台</p>
      </div>
      <div className="flex gap-1.5 bg-slate-900 p-1 rounded-xl border border-slate-800 self-start shrink-0">
        {filters.map((filter) => {
          const count = allApprovals.filter((a) => filter === 'ALL' || a.status.toUpperCase() === filter).length;
          const active = auditFilter === filter;

          return (
            <button
              key={filter}
              type="button"
              onClick={() => {
                setAuditFilter(filter);
                setSelectedApprovalId(null);
              }}
              className={`px-3 py-1.5 rounded-lg text-xs font-semibold tracking-wide transition flex items-center gap-1.5 ${
                active
                  ? 'bg-indigo-600 text-white shadow-lg shadow-indigo-600/10'
                  : 'text-slate-400 hover:text-slate-200 bg-transparent'
              }`}
            >
              <span>{labelMap[filter]}</span>
              <span
                className={`text-[10px] px-1 rounded-md ${
                  active ? 'bg-indigo-700 text-white' : 'bg-slate-800 text-slate-500'
                }`}
              >
                {count}
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
