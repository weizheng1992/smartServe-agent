import type React from 'react';
import type { PendingApprovalRecord } from 'types';
import { ApprovalRiskBadge, CheckCircle2, User } from 'ui';
import type { AuditFilterType } from './ApprovalFilterHeader';

interface ApprovalListProps {
  allApprovals: PendingApprovalRecord[];
  auditFilter: AuditFilterType;
  selectedApprovalId: string | null;
  setSelectedApprovalId: (id: string | null) => void;
}

export function ApprovalList({
  allApprovals,
  auditFilter,
  selectedApprovalId,
  setSelectedApprovalId,
}: ApprovalListProps) {
  const filteredApprovals = allApprovals.filter((a) => auditFilter === 'ALL' || a.status.toUpperCase() === auditFilter);

  return (
    <div className="w-80 md:w-96 flex flex-col bg-slate-900/40 rounded-2xl border border-slate-900 overflow-y-auto shrink-0 p-3 space-y-2">
      <span className="text-[10px] font-bold text-slate-500 tracking-wider uppercase block px-2 mb-1">
        安全审核工单清单 ({filteredApprovals.length})
      </span>
      {filteredApprovals.length === 0 ? (
        <div className="py-20 text-center flex flex-col items-center justify-center gap-3">
          <CheckCircle2 className="h-8 w-8 text-slate-700 animate-pulse" />
          <span className="text-xs text-slate-500 font-medium">当前列表下没有任何审核工单</span>
        </div>
      ) : (
        filteredApprovals.map((item) => {
          const active = selectedApprovalId === item.id;
          const dateStr = item.createdAt
            ? new Date(item.createdAt).toLocaleString([], {
                month: '2-digit',
                day: '2-digit',
                hour: '2-digit',
                minute: '2-digit',
              })
            : '';

          const customerDisplay = item.userEmail || (item.userId ? `ID: ${item.userId.substring(0, 8)}...` : '');

          return (
            <button
              key={item.id}
              type="button"
              onClick={() => setSelectedApprovalId(item.id)}
              className={`w-full text-left p-3.5 rounded-xl border transition group ${
                active
                  ? 'bg-indigo-600/10 border-indigo-500/30'
                  : 'bg-slate-900 border-slate-850/60 hover:bg-slate-850/40 hover:border-slate-800'
              }`}
            >
              <div className="flex items-center justify-between gap-2 mb-2">
                <span className="text-xs font-bold text-slate-200 truncate font-mono">
                  ID: {item.id.substring(0, 8)}...
                </span>
                <ApprovalRiskBadge actionType={item.actionType} status={item.status} />
              </div>
              <div className="text-xs text-slate-300 font-semibold mb-1">
                动作类别: <span className="text-indigo-400 font-bold">{item.actionType || '未知'}</span>
              </div>
              {customerDisplay && (
                <div className="flex items-center space-x-1 text-[11px] text-emerald-400/90 font-mono my-1 truncate">
                  <User className="h-3 w-3 shrink-0" />
                  <span className="truncate">{customerDisplay}</span>
                </div>
              )}
              <div className="flex items-center justify-between mt-2 pt-2 border-t border-slate-800/60 text-[10px] text-slate-500 font-mono">
                <span>{dateStr}</span>
                <span className="truncate max-w-[130px]">
                  会话: {item.threadId ? `${item.threadId.substring(0, 8)}...` : ''}
                </span>
              </div>
            </button>
          );
        })
      )}
    </div>
  );
}
