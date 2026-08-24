import React from 'react';

export function EvalMetricsSummary() {
  return (
    <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
      <div className="p-4 bg-white border border-slate-200 rounded-xl shadow-xs">
        <div className="text-xs font-semibold text-slate-500">平均工具调用准确率</div>
        <div className="text-2xl font-bold text-slate-900 mt-1">98.2%</div>
        <div className="text-[11px] text-emerald-600 font-medium mt-1">↑ +2.4% 相比上周基线</div>
      </div>
      <div className="p-4 bg-white border border-slate-200 rounded-xl shadow-xs">
        <div className="text-xs font-semibold text-slate-500">RAG 知识检索忠实度</div>
        <div className="text-2xl font-bold text-slate-900 mt-1">95.6%</div>
        <div className="text-[11px] text-blue-600 font-medium mt-1">Contextual Retrieval 增益</div>
      </div>
      <div className="p-4 bg-white border border-slate-200 rounded-xl shadow-xs">
        <div className="text-xs font-semibold text-slate-500">自动拦截/HITL 触发率</div>
        <div className="text-2xl font-bold text-amber-600 mt-1">12.0%</div>
        <div className="text-[11px] text-slate-400 font-medium mt-1">风控策略严格符合预期</div>
      </div>
    </div>
  );
}
