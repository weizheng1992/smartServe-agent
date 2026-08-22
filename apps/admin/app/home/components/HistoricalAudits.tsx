import type React from "react";
import { useState } from "react";
import {
  ApprovalContextDrawer,
  ApprovalRiskBadge,
  ArrowRight,
  Badge,
  Button,
  Card,
  CheckCircle2,
  DollarSign,
  Layers,
  Package,
  ScrollArea,
  getApprovalContextData,
} from "ui";
import type { Approval } from "../hooks/types";

interface HistoricalAuditsProps {
  auditedApprovals: Approval[];
}

export function HistoricalAudits({ auditedApprovals }: HistoricalAuditsProps) {
  const [selectedAudit, setSelectedAudit] = useState<Approval | null>(null);

  return (
    <section className="space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center space-x-2">
          <CheckCircle2 className="h-5 w-5 text-slate-500" />
          <h2 className="text-sm font-bold tracking-wider uppercase text-slate-400">
            📁 历史核签审计归档记录 ({auditedApprovals.length})
          </h2>
        </div>
        <span className="text-[10px] font-mono text-slate-500">
          点击任意工单记录可调出触发风控归因、用户画像与聊天全景
        </span>
      </div>

      <Card className="bg-slate-900 border-slate-800 overflow-hidden shadow-xl">
        <ScrollArea className="w-full">
          <table className="w-full text-left border-collapse text-xs">
            <thead>
              <tr className="border-b border-slate-800 bg-slate-950/40 text-slate-500 font-mono font-bold tracking-wider">
                <th className="p-4">工单 ID</th>
                <th className="p-4">业务场景</th>
                <th className="p-4">操作类型</th>
                <th className="p-4">触发归因与业务上下文</th>
                <th className="p-4">完成状态</th>
                <th className="p-4">审计时间</th>
                <th className="p-4 text-right">全景溯源</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/80">
              {auditedApprovals.length === 0 ? (
                <tr>
                  <td
                    colSpan={7}
                    className="p-8 text-center text-slate-500 font-mono"
                  >
                    No historical audit records found.
                  </td>
                </tr>
              ) : (
                auditedApprovals.map((app) => {
                  const context = getApprovalContextData(app);
                  const commentRaw = app.actionPayload?.rejectionReason || "";
                  const comment =
                    typeof commentRaw === "string"
                      ? commentRaw
                      : JSON.stringify(commentRaw);

                  return (
                    <tr
                      key={app.id}
                      onClick={() => setSelectedAudit(app)}
                      className="hover:bg-slate-950/40 transition-colors cursor-pointer group"
                    >
                      <td className="p-4 font-mono text-slate-300 font-semibold group-hover:text-indigo-300 transition-colors">
                        {app.id.substring(0, 8)}...
                      </td>
                      <td className="p-4 font-mono">
                        <Badge
                          variant="outline"
                          className="bg-slate-950 border-slate-850 text-indigo-400 font-semibold uppercase tracking-wider text-[9px]"
                        >
                          {app.businessId || "ecommerce"}
                        </Badge>
                      </td>
                      <td className="p-4 font-bold text-slate-300">
                        <div className="space-y-1">
                          <span>{app.actionType}</span>
                          {context.orderId && (
                            <div className="font-mono text-[10px] text-slate-500">
                              {context.orderId}
                            </div>
                          )}
                        </div>
                      </td>
                      <td className="p-4 max-w-[320px]">
                        <div className="font-mono text-[10px] text-slate-400 bg-slate-950/60 border border-slate-850 p-2.5 rounded-lg space-y-1.5">
                          {/* Type specific highlight */}
                          {context.category === "refund" &&
                            context.refundAmount !== undefined && (
                              <div className="text-rose-400 font-bold flex items-center gap-1 font-mono">
                                <DollarSign className="h-3 w-3" />
                                <span>
                                  退款金额: ¥{" "}
                                  {Number(context.refundAmount).toFixed(2)}
                                </span>
                              </div>
                            )}

                          {context.category === "address" &&
                            context.newAddress && (
                              <div className="text-amber-300 font-bold flex items-center gap-1">
                                <Package className="h-3 w-3 shrink-0" />
                                <span className="truncate">
                                  新地址: {context.newAddress}
                                </span>
                              </div>
                            )}

                          {context.userInput && (
                            <div className="text-slate-300 font-sans text-[11px] bg-slate-900/80 p-1.5 rounded border border-slate-800">
                              <span className="text-slate-500 text-[9px] block">
                                用户诉求/提问:
                              </span>
                              <span className="line-clamp-2">
                                &quot;{context.userInput}&quot;
                              </span>
                            </div>
                          )}

                          {context.reason && (
                            <div className="text-amber-400/90 font-sans text-[10px]">
                              原因: {context.reason}
                            </div>
                          )}

                          {comment && (
                            <div className="border-t border-slate-800 pt-1 text-rose-400 font-sans truncate">
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
                      <td className="p-4 text-right">
                        <Button
                          type="button"
                          size="sm"
                          onClick={(e) => {
                            e.stopPropagation();
                            setSelectedAudit(app);
                          }}
                          className="h-7 text-[11px] bg-slate-800 hover:bg-slate-700 text-indigo-300 border border-slate-700 px-2.5 rounded-lg flex items-center gap-1 ml-auto"
                        >
                          <Layers className="h-3 w-3" />
                          <span>排查全景</span>
                        </Button>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </ScrollArea>
      </Card>

      {/* 🔍 Historical Audit Context Drawer */}
      <ApprovalContextDrawer
        isOpen={Boolean(selectedAudit)}
        onClose={() => setSelectedAudit(null)}
        approval={selectedAudit}
      />
    </section>
  );
}
