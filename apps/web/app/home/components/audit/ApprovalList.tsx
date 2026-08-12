import type React from "react";
import { CheckCircle2 } from "ui";
import type { PendingApprovalRecord } from "types";
import type { AuditFilterType } from "./ApprovalFilterHeader";

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
  const filteredApprovals = allApprovals.filter(
    (a) => auditFilter === "ALL" || a.status.toUpperCase() === auditFilter,
  );

  return (
    <div className="w-80 md:w-96 flex flex-col bg-slate-900/40 rounded-2xl border border-slate-900 overflow-y-auto shrink-0 p-3 space-y-2">
      <span className="text-[10px] font-bold text-slate-500 tracking-wider uppercase block px-2 mb-1">
        安全审核工单清单 ({filteredApprovals.length})
      </span>
      {filteredApprovals.length === 0 ? (
        <div className="py-20 text-center flex flex-col items-center justify-center gap-3">
          <CheckCircle2 className="h-8 w-8 text-slate-700 animate-pulse" />
          <span className="text-xs text-slate-500 font-medium">
            当前列表下没有任何审核工单
          </span>
        </div>
      ) : (
        filteredApprovals.map((item) => {
          const active = selectedApprovalId === item.id;
          const dateStr = item.createdAt
            ? new Date(item.createdAt).toLocaleString([], {
                month: "2-digit",
                day: "2-digit",
                hour: "2-digit",
                minute: "2-digit",
              })
            : "";

          const badgeStyle =
            {
              waiting: "bg-amber-500/10 text-amber-400 border-amber-500/20",
              approved:
                "bg-emerald-500/10 text-emerald-400 border-emerald-500/20",
              rejected: "bg-rose-500/10 text-rose-400 border-rose-500/20",
              expired: "bg-slate-800 text-slate-500 border-transparent",
            }[item.status as "waiting" | "approved" | "rejected" | "expired"] ||
            "bg-slate-800 text-slate-400 border-transparent";

          const statusTextMap: Record<string, string> = {
            waiting: "待审批",
            approved: "已核准",
            rejected: "已驳回",
            expired: "已超时",
          };

          return (
            <button
              key={item.id}
              type="button"
              onClick={() => setSelectedApprovalId(item.id)}
              className={`w-full text-left p-3.5 rounded-xl border transition group ${
                active
                  ? "bg-indigo-600/10 border-indigo-500/30"
                  : "bg-slate-900 border-slate-850/60 hover:bg-slate-850/40 hover:border-slate-800"
              }`}
            >
              <div className="flex items-center justify-between gap-2 mb-2">
                <span className="text-xs font-bold text-slate-200 truncate font-mono">
                  ID: {item.id.substring(0, 8)}...
                </span>
                <span
                  className={`text-[10px] font-bold px-1.5 py-0.5 rounded border ${badgeStyle}`}
                >
                  {statusTextMap[item.status] || item.status}
                </span>
              </div>
              <div className="text-xs text-slate-300 font-semibold mb-1">
                动作类别:{" "}
                <span className="text-indigo-400 font-bold">
                  {item.actionType || "未知"}
                </span>
              </div>
              <div className="flex items-center justify-between mt-2.5 pt-2 border-t border-slate-800/60 text-[10px] text-slate-500 font-mono">
                <span>{dateStr}</span>
                <span className="truncate max-w-[150px]">
                  会话:{" "}
                  {item.threadId ? `${item.threadId.substring(0, 10)}...` : ""}
                </span>
              </div>
            </button>
          );
        })
      )}
    </div>
  );
}
