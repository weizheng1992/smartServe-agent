import type React from "react";
import {
  Badge,
  Card,
  CardContent,
  Clock,
  Cpu,
  DollarSign,
  Layers,
  TrendingUp,
} from "ui";
import type { AnalyticsSummary } from "../hooks/types";

interface MetricsProps {
  summary: AnalyticsSummary;
}

export function Metrics({ summary }: MetricsProps) {
  return (
    <section className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-4">
      <Card className="bg-slate-900/60 border-slate-800/80 relative overflow-hidden group">
        <CardContent className="p-5 space-y-2">
          <div className="absolute right-4 top-4 opacity-5 group-hover:opacity-10 transition">
            <DollarSign className="h-14 w-14 text-white" />
          </div>
          <div className="flex justify-between items-center">
            <span className="text-[10px] font-bold text-slate-500 uppercase tracking-widest block font-mono">
              TOTAL ACCRUED COST
            </span>
            <Badge
              variant="outline"
              className="border-emerald-500/20 text-emerald-400 bg-emerald-950/20 text-[9px] font-mono"
            >
              Cost Metric
            </Badge>
          </div>
          <div className="flex items-baseline gap-1">
            <span className="text-2xl font-bold font-mono text-emerald-400">
              ${summary.totalCostUsd.toFixed(5)}
            </span>
            <span className="text-[10px] text-slate-500 font-mono">USD</span>
          </div>
          <span className="text-[10px] text-slate-400 block mt-1">
            商户算力总损耗 (Gemini 3.5)
          </span>
        </CardContent>
      </Card>

      <Card className="bg-slate-900/60 border-slate-800/80 relative overflow-hidden group">
        <CardContent className="p-5 space-y-2">
          <div className="absolute right-4 top-4 opacity-5 group-hover:opacity-10 transition">
            <Layers className="h-14 w-14 text-white" />
          </div>
          <div className="flex justify-between items-center">
            <span className="text-[10px] font-bold text-slate-500 uppercase tracking-widest block font-mono">
              TOTAL CONVERSATIONS
            </span>
            <Badge
              variant="outline"
              className="border-indigo-500/20 text-indigo-400 bg-indigo-950/20 text-[9px] font-mono"
            >
              Session Count
            </Badge>
          </div>
          <div className="text-2xl font-bold font-mono text-indigo-400">
            {summary.totalSessions}
          </div>
          <span className="text-[10px] text-slate-400 block mt-1">
            会话线程物理总数
          </span>
        </CardContent>
      </Card>

      <Card className="bg-slate-900/60 border-slate-800/80 relative overflow-hidden group">
        <CardContent className="p-5 space-y-2">
          <div className="absolute right-4 top-4 opacity-5 group-hover:opacity-10 transition">
            <Clock className="h-14 w-14 text-white" />
          </div>
          <div className="flex justify-between items-center">
            <span className="text-[10px] font-bold text-slate-500 uppercase tracking-widest block font-mono">
              AVERAGE LATENCY
            </span>
            <Badge
              variant="outline"
              className="border-amber-500/20 text-amber-400 bg-amber-950/20 text-[9px] font-mono"
            >
              Latency
            </Badge>
          </div>
          <div className="flex items-baseline gap-1">
            <span className="text-2xl font-bold font-mono text-amber-400">
              {summary.avgLatencyMs}
            </span>
            <span className="text-[10px] text-slate-500 font-mono">MS</span>
          </div>
          <span className="text-[10px] text-slate-400 block mt-1">
            单次对话全图决策平均耗时
          </span>
        </CardContent>
      </Card>

      <Card className="bg-slate-900/60 border-slate-800/80 relative overflow-hidden group">
        <CardContent className="p-5 space-y-2">
          <div className="absolute right-4 top-4 opacity-5 group-hover:opacity-10 transition">
            <Cpu className="h-14 w-14 text-white" />
          </div>
          <div className="flex justify-between items-center">
            <span className="text-[10px] font-bold text-slate-500 uppercase tracking-widest block font-mono">
              AVERAGE TOKENS
            </span>
            <Badge
              variant="outline"
              className="border-slate-700 text-slate-300 bg-slate-800/40 text-[9px] font-mono"
            >
              Token Consumption
            </Badge>
          </div>
          <div className="text-2xl font-bold font-mono text-slate-200">
            {summary.avgTokens}
          </div>
          <span className="text-[10px] text-slate-400 block mt-1">
            单会话大模型 Token 平均损耗
          </span>
        </CardContent>
      </Card>

      <Card className="bg-slate-900/60 border-slate-800/80 relative overflow-hidden group col-span-1 sm:col-span-2 lg:col-span-1">
        <CardContent className="p-5 space-y-2">
          <div className="absolute right-4 top-4 opacity-5 group-hover:opacity-10 transition">
            <TrendingUp className="h-14 w-14 text-white" />
          </div>
          <div className="flex justify-between items-center">
            <span className="text-[10px] font-bold text-slate-500 uppercase tracking-widest block font-mono">
              AUTOPILOT SUCCESS
            </span>
            <Badge
              variant="outline"
              className="border-emerald-500/20 text-emerald-400 bg-emerald-950/20 text-[9px] font-mono"
            >
              Resolution
            </Badge>
          </div>
          <div className="flex items-baseline gap-1">
            <span className="text-2xl font-bold font-mono text-emerald-400">
              {summary.autopilotRate}%
            </span>
          </div>
          <span className="text-[10px] text-slate-400 block mt-1">
            AI 自主解决率 / 免审批放行比
          </span>
        </CardContent>
      </Card>
    </section>
  );
}
