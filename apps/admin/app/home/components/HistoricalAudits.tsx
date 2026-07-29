import type React from "react";
import { CheckCircle2 } from "ui";
import { Approval } from "../hooks/types";

interface HistoricalAuditsProps {
  auditedApprovals: Approval[];
}

export function HistoricalAudits({ auditedApprovals }: HistoricalAuditsProps) {
  return (
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
                  const comment = app.actionPayload?.rejectionReason || "";

                  return (
                    <tr key={app.id} className="hover:bg-slate-950/20 transition-colors">
                      <td className="p-4 font-mono text-slate-300">{app.id.substring(0, 8)}...</td>
                      <td className="p-4 font-mono">
                        <span className="px-2 py-0.5 rounded bg-slate-950 border border-slate-850 text-slate-400 font-semibold uppercase tracking-wider text-[9px]">
                          {app.businessId || "ecommerce"}
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
                            app.status === "approved"
                              ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/15"
                              : app.status === "rejected"
                                ? "bg-rose-500/10 text-rose-400 border border-rose-500/15"
                                : "bg-slate-500/10 text-slate-400 border border-slate-800"
                          }`}
                        >
                          {app.status}
                        </span>
                      </td>
                      <td className="p-4 font-mono text-slate-500">
                        {new Date(app.createdAt).toLocaleString([], {
                          month: "2-digit",
                          day: "2-digit",
                          hour: "2-digit",
                          minute: "2-digit",
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
  );
}
