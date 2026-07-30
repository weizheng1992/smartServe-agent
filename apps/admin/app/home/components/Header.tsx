import type React from 'react';
import { Lock, RefreshCw } from 'ui';

interface HeaderProps {
  selectedMerchant: string;
  setSelectedMerchant: (m: string) => void;
  isRefreshing: boolean;
  fetchDashboardData: () => Promise<void>;
}

export function Header({ selectedMerchant, setSelectedMerchant, isRefreshing, fetchDashboardData }: HeaderProps) {
  return (
    <header className="px-8 py-5 border-b border-slate-800 bg-slate-900/40 backdrop-blur-md sticky top-0 z-40 flex flex-col md:flex-row justify-between items-start md:items-center gap-4">
      <div className="flex items-center space-x-3.5">
        <div className="h-10 w-10 rounded-xl bg-indigo-600 flex items-center justify-center shadow-lg shadow-indigo-500/20 shrink-0">
          <Lock className="h-5 w-5 text-white" />
        </div>
        <div>
          <h1 className="text-lg font-bold tracking-tight text-slate-200">smartServe 客服大盘 & 安全核签中心</h1>
          <p className="text-xs text-slate-500 mt-0.5">
            企业级多租户 Human-in-the-Loop 审批流与 APM 财务算力监控控制台
          </p>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        {/* Merchant Selector */}
        <div className="flex items-center space-x-1 bg-slate-900 border border-slate-800 p-1 rounded-xl">
          {['ecommerce', 'nike', 'adidas', 'puma'].map((m) => (
            <button
              type="button"
              key={m}
              onClick={() => setSelectedMerchant(m)}
              className={`px-3 py-1.5 rounded-lg text-xs font-semibold uppercase tracking-wider transition ${
                selectedMerchant === m
                  ? 'bg-indigo-600 text-white shadow-md'
                  : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/40'
              }`}
            >
              {m}
            </button>
          ))}
        </div>

        <button
          type="button"
          onClick={fetchDashboardData}
          className="h-9 w-9 flex items-center justify-center rounded-xl bg-slate-900 border border-slate-800 text-slate-400 hover:text-slate-200 transition"
        >
          <RefreshCw className={`h-4 w-4 ${isRefreshing ? 'animate-spin text-indigo-400' : ''}`} />
        </button>
      </div>
    </header>
  );
}
