import type React from "react";
import { ApprovalRiskBadge, Badge, Card, CheckCircle2, ScrollArea } from "ui";
import type { Approval } from "../hooks/types";

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

      <Card className="bg-slate-900 border-slate-800 overflow-hidden shadow-xl">
        <ScrollArea className="w-full">
          <table className="w-full text-left border-collapse text-xs">
            <thead>
              <tr className="border-b border-slate-800 bg-slate-950/40 text-slate-500 font-mono font-bold tracking-wider">
                <th className="p-4">工单 ID</th>
                <th className="p-4">业务场景</th>
                <th className="p-4">操作类型</th>
                <th className="p-4">数据详情</th>
                <th className="p-4">完成状态</th>
                <th className="p-4">审计时间</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/80">
              {auditedApprovals.length === 0 ? (
                <tr>
                  <td
                    colSpan={6}
                    className="p-8 text-center text-slate-500 font-mono"
                  >
                    No historical audit records found.
                  </td>
                </tr>
              ) : (
                auditedApprovals.map((app) => {
                  const args = app.actionPayload?.args || {};
                  const commentRaw = app.actionPayload?.rejectionReason || "";
                  const comment =
                    typeof commentRaw === "string"
                      ? commentRaw
                      : JSON.stringify(commentRaw);

                  return (
                    <tr
                      key={app.id}
                      className="hover:bg-slate-950/20 transition-colors"
                    >
                      <td className="p-4 font-mono text-slate-300">
                        {app.id.substring(0, 8)}...
                      </td>
                      <td className="p-4 font-mono">
                        <Badge
                          variant="outline"
                          className="bg-slate-950 border-slate-800 text-slate-400 font-semibold uppercase tracking-wider text-[9px]"
                        >
                          {app.businessId || "ecommerce"}
                        </Badge>
                      </td>
                      <td className="p-4 font-bold text-slate-300">
                        {app.actionType}
                      </td>
                      <td className="p-4 max-w-[250px]">
                        <div className="font-mono text-[10px] text-slate-400 bg-slate-950/40 border border-slate-800/60 p-2 rounded-lg space-y-1">
                          {Object.entries(args).map(([k, v]) => (
                            <div key={k} className="truncate">
                              {k}:{" "}
                              <span className="text-slate-200">
                                {String(v)}
                              </span>
                            </div>
                          ))}
                          {comment && (
                            <div className="border-t border-slate-800/60 pt-1 text-rose-400 font-sans truncate">
                              驳回理由: {comment}
                            </div>
                          )}
                        </div>
                      </td>
                      <td className="p-4">
                        <ApprovalRiskBadge
                          actionType={app.actionType}
                          status={app.status}
                        />
                      </td>
                      <td className="p-4 font-mono text-slate-500">
                        {app.createdAt
                          ? new Date(app.createdAt).toLocaleString([], {
                              month: "2-digit",
                              day: "2-digit",
                              hour: "2-digit",
                              minute: "2-digit",
                            })
                          : "-"}
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </ScrollArea>
      </Card>
    </section>
  );
}
