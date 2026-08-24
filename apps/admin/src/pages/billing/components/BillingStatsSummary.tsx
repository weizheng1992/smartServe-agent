import React from 'react';

export function BillingStatsSummary() {
  return (
    <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
      <div className="p-4 bg-white border border-slate-200 rounded-xl shadow-xs">
        <div className="text-xs font-semibold text-slate-500">全平台本月 Token 总消耗</div>
        <div className="text-2xl font-bold text-slate-900 mt-1">2,732,500</div>
        <div className="text-[11px] text-slate-400 mt-1">涵盖 GPT-4o-mini / Gemini-1.5-pro</div>
      </div>
      <div className="p-4 bg-white border border-slate-200 rounded-xl shadow-xs">
        <div className="text-xs font-semibold text-slate-500">本月模型总费用支出</div>
        <div className="text-2xl font-bold text-emerald-600 mt-1">$10.93 USD</div>
        <div className="text-[11px] text-emerald-600 font-medium mt-1">按调用量实时统计</div>
      </div>
      <div className="p-4 bg-white border border-slate-200 rounded-xl shadow-xs">
        <div className="text-xs font-semibold text-slate-500">全自动解决率 (Autopilot)</div>
        <div className="text-2xl font-bold text-blue-600 mt-1">92.4%</div>
        <div className="text-[11px] text-slate-400 mt-1">无需人工客服介入率</div>
      </div>
    </div>
  );
}
