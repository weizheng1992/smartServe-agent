import type React from "react";
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  CheckCircle2,
  Input,
  Loader2,
  XCircle,
} from "ui";
import { Cpu, Shield, Clock } from "lucide-react";
import { TaskPlan } from "../hooks/types";

interface APMPanelProps {
  tokensConsumed: number;
  pendingApprovalsList: any[];
  rejectionInput: string;
  setRejectionReason: (val: string) => void;
  runningDetails: any[];
  activePlan: TaskPlan | null;
  handleApprovalAction: (approvalId: string, action: "approve" | "reject") => Promise<void>;
}

export function APMPanel({
  tokensConsumed,
  pendingApprovalsList,
  rejectionInput,
  setRejectionReason,
  runningDetails,
  activePlan,
  handleApprovalAction,
}: APMPanelProps) {
  return (
    <section className="w-full md:w-96 bg-slate-900/50 p-6 flex flex-col justify-between border-t md:border-t-0 border-slate-800 overflow-hidden">
      <div className="space-y-6 flex-1 flex flex-col min-h-0 mb-4">
        <div className="flex items-center justify-between shrink-0">
          <div className="flex items-center space-x-2">
            <Cpu className="h-4.5 w-4.5 text-indigo-400 animate-spin-slow shrink-0" />
            <h2 className="text-sm font-bold tracking-wider text-slate-200 uppercase">
              有向有环图（DAG）实时执行监控
            </h2>
          </div>
          {tokensConsumed > 0 && (
            <Badge
              variant="outline"
              className="border-indigo-500/30 text-indigo-400 bg-indigo-950/10 font-mono text-[10px] px-1.5 py-0.5 shrink-0"
            >
              {tokensConsumed} Tokens
            </Badge>
          )}
        </div>

        <div className="flex-1 overflow-y-auto pr-2 min-h-0">
          <div className="space-y-4">
            {/* 🛡️ HUMAN-IN-THE-LOOP (HITL) 人工授权核准/模拟后台审批面板 */}
            {pendingApprovalsList.length > 0 && (
              <Card className="border-amber-500/50 bg-amber-950/20 shadow-2xl animate-pulse border-l-4 border-l-amber-500 rounded-xl overflow-hidden">
                <CardHeader className="p-3.5 pb-2 border-b border-amber-500/15 bg-amber-500/5">
                  <div className="flex items-center space-x-2">
                    <Shield className="h-4.5 w-4.5 text-amber-400 animate-bounce shrink-0" />
                    <span className="text-[11px] font-bold text-amber-300 uppercase tracking-wider">
                      🛡️ 安全红线拦截：待人工核准放行
                    </span>
                  </div>
                </CardHeader>
                <CardContent className="p-3.5 space-y-3">
                  <div className="text-xs text-slate-300 leading-relaxed font-sans">
                    决策引擎拦截了高危动作：
                    <strong className="text-amber-300 font-semibold">
                      {pendingApprovalsList[0].actionType}
                    </strong>
                    。
                    <div className="mt-1.5 text-[10px] text-slate-400 font-mono bg-slate-950/40 p-2 rounded border border-slate-850 overflow-x-auto">
                      参数: {JSON.stringify(pendingApprovalsList[0].actionPayload?.args || {})}
                    </div>
                  </div>

                  <div className="space-y-2">
                    <Input
                      type="text"
                      value={rejectionInput}
                      onChange={(e) => setRejectionReason(e.target.value)}
                      placeholder="若驳回，请在此处输入拒绝原因..."
                      className="w-full bg-slate-950 text-xs py-1 border-slate-850 focus-visible:ring-amber-500 text-slate-100 rounded-lg placeholder-slate-600"
                    />
                    <div className="flex gap-2">
                      <Button
                        onClick={() => handleApprovalAction(pendingApprovalsList[0].id, "approve")}
                        className="flex-1 bg-emerald-600 hover:bg-emerald-500 text-white rounded-lg h-8 text-[10px] font-bold transition flex items-center justify-center space-x-1"
                      >
                        <CheckCircle2 className="h-3 w-3" />
                        <span>核准放行 (Approve)</span>
                      </Button>
                      <Button
                        onClick={() => handleApprovalAction(pendingApprovalsList[0].id, "reject")}
                        variant="destructive"
                        className="flex-1 bg-rose-600 hover:bg-rose-500 text-white rounded-lg h-8 text-[10px] font-bold transition flex items-center justify-center space-x-1"
                      >
                        <XCircle className="h-3 w-3" />
                        <span>驳回申请 (Reject)</span>
                      </Button>
                    </div>
                  </div>
                </CardContent>
              </Card>
            )}

            {runningDetails.length === 0 ? (
              <div className="py-20 text-center space-y-3">
                <Clock className="h-8 w-8 text-slate-600 mx-auto animate-pulse" />
                <p className="text-xs text-slate-500 leading-relaxed">
                  等待触发会话...
                  <br />
                  输入消息后，此处将呈现详细的后台运行节点数据流。
                </p>
              </div>
            ) : (
              runningDetails.map((log, lIdx) => (
                <Card
                  key={lIdx}
                  className="bg-slate-950/60 border-slate-800 shadow-lg border-l-2 border-l-indigo-500"
                >
                  <CardHeader className="p-3 pb-1.5 flex flex-row items-center justify-between space-y-0">
                    <Badge className="bg-indigo-500/10 text-indigo-400 border border-indigo-500/20 rounded-md font-mono text-[10px] px-2 py-0.5">
                      {log.node}
                    </Badge>
                    <span className="text-[9px] text-slate-500 font-mono">STEP {lIdx + 1}</span>
                  </CardHeader>
                  <CardContent className="p-3 pt-0 space-y-2">
                    <p className="text-xs text-slate-300 leading-relaxed font-medium">{log.desc}</p>
                    <div className="bg-slate-900/80 p-2.5 rounded-lg border border-slate-850/80">
                      <span className="text-[10px] text-slate-500 block font-mono uppercase tracking-wider mb-1">
                        执行反馈/输出
                      </span>
                      <span
                        className={`text-xs font-mono leading-relaxed block whitespace-pre-wrap ${log.resultText.includes("❌") || log.resultText.includes("failed") ? "text-rose-400" : "text-emerald-400"}`}
                      >
                        {log.resultText}
                      </span>
                    </div>
                  </CardContent>
                </Card>
              ))
            )}

            {/* Live planning box at the bottom */}
            {activePlan && (
              <Card className="border-indigo-500/40 bg-indigo-950/10 shadow-2xl animate-fade-in border-l-2 border-l-indigo-400">
                <CardHeader className="p-3 pb-2 border-b border-indigo-500/15">
                  <div className="flex items-center space-x-2">
                    <Loader2 className="h-3.5 w-3.5 animate-spin text-indigo-400" />
                    <span className="text-[11px] font-bold text-indigo-300 uppercase tracking-wider">
                      实时生成执行规划图
                    </span>
                  </div>
                </CardHeader>

                <CardContent className="p-3 space-y-2">
                  <div className="text-[10px] text-slate-400 mb-1 font-semibold">目标: {activePlan.goal}</div>
                  {activePlan.subtasks.map((step) => (
                    <div
                      key={step.id}
                      className="flex items-center justify-between text-[11px] bg-slate-950/80 p-2 rounded-lg border border-slate-850"
                    >
                      <span className="text-slate-300 truncate pr-2 max-w-[180px]">{step.description}</span>
                      <Badge
                        variant={
                          step.status === "completed"
                            ? "success"
                            : step.status === "executing"
                              ? "default"
                              : "outline"
                        }
                        className={`text-[9px] px-1.5 py-0 shadow-none ${
                          step.status === "completed"
                            ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/15"
                            : step.status === "executing"
                              ? "bg-indigo-500/15 text-indigo-400 border border-indigo-500/20"
                              : "border-slate-800 text-slate-500"
                        }`}
                      >
                        {step.status === "completed"
                          ? "已完成"
                          : step.status === "executing"
                            ? "执行中"
                            : "未开始"}
                      </Badge>
                    </div>
                  ))}
                </CardContent>
              </Card>
            )}
          </div>
        </div>
      </div>

      <div className="pt-4 border-t border-slate-800 space-y-3.5">
        <div>
          <span className="text-[10px] text-slate-500 font-mono tracking-wider uppercase block">
            观测探针运行状态
          </span>
          <span className="text-xs text-slate-400 font-medium mt-1 block flex items-center gap-1.5">
            <span className="h-2 w-2 rounded-full bg-emerald-500 animate-pulse shrink-0" />
            本地 LangGraph 探针已激活
          </span>
        </div>

        <div className="pt-3 border-t border-slate-800/60">
          <span className="text-[10px] text-slate-500 font-mono tracking-wider uppercase block">
            单次会话算力消耗
          </span>
          <span className="text-xs text-indigo-400 font-mono font-medium mt-1 block flex items-center gap-1.5">
            <Cpu className="h-3.5 w-3.5 animate-pulse shrink-0" />
            <span>
              已消耗 Token: <strong className="text-slate-100 font-bold text-sm">{tokensConsumed}</strong>
            </span>
          </span>
        </div>
      </div>
    </section>
  );
}
