import type React from 'react';
import { Badge, Button, Lock, RefreshCw } from 'ui';

interface HeaderProps {
  selectedMerchant: string;
  setSelectedMerchant: (m: string) => void;
  isRefreshing: boolean;
  fetchDashboardData: () => Promise<void>;
  onStartActiveTakeover?: () => void;
}

export function Header({
  selectedMerchant,
  setSelectedMerchant,
  isRefreshing,
  fetchDashboardData,
  onStartActiveTakeover,
}: HeaderProps) {
  return (
    <header className="px-8 py-5 border-b border-slate-800 bg-slate-900/40 backdrop-blur-md sticky top-0 z-40 flex flex-col md:flex-row justify-between items-start md:items-center gap-4">
      <div className="flex items-center space-x-3.5">
        <div className="h-10 w-10 rounded-xl bg-indigo-600 flex items-center justify-center shadow-lg shadow-indigo-500/20 shrink-0">
          <Lock className="h-5 w-5 text-white" />
        </div>
        <div>
          <div className="flex items-center space-x-2">
            <h1 className="text-lg font-bold tracking-tight text-slate-200">smartServe 客服大盘 & 安全核签中心</h1>
            <Badge
              variant="outline"
              className="border-indigo-500/30 text-indigo-400 bg-indigo-950/20 font-mono text-[10px] uppercase font-bold"
            >
              Enterprise Admin
            </Badge>
          </div>
          <p className="text-xs text-slate-500 mt-0.5">
            企业级多租户 Human-in-the-Loop 审批流与 APM 财务算力监控控制台
          </p>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        {/* Active Takeover IM Button */}
        {onStartActiveTakeover && (
          <Button
            type="button"
            variant="default"
            size="sm"
            onClick={onStartActiveTakeover}
            className="h-9 px-3.5 text-xs font-bold bg-indigo-600 hover:bg-indigo-500 text-white rounded-xl shadow-lg shadow-indigo-600/20 flex items-center gap-1.5"
          >
            <span>⚡ 客服随时主动接管 (IM 对话)</span>
          </Button>
        )}

        {/* Merchant Selector using shadcn Buttons */}
        <div className="flex items-center space-x-1 bg-slate-900 border border-slate-800 p-1 rounded-xl">
          {['ecommerce', 'nike', 'adidas', 'puma'].map((m) => {
            const isSelected = selectedMerchant === m;
            return (
              <Button
                type="button"
                key={m}
                size="sm"
                variant={isSelected ? 'default' : 'ghost'}
                onClick={() => setSelectedMerchant(m)}
                className={`h-7 px-3 text-xs font-semibold uppercase tracking-wider rounded-lg transition-colors ${
                  isSelected
                    ? 'bg-indigo-600 text-white shadow-md hover:bg-indigo-500'
                    : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/60'
                }`}
              >
                {m}
              </Button>
            );
          })}
        </div>

        {/* Refresh Action using shadcn Button */}
        <Button
          type="button"
          variant="outline"
          size="icon"
          onClick={fetchDashboardData}
          className="h-9 w-9 rounded-xl bg-slate-900 border-slate-800 text-slate-400 hover:text-slate-200 hover:bg-slate-800"
        >
          <RefreshCw className={`h-4 w-4 ${isRefreshing ? 'animate-spin text-indigo-400' : ''}`} />
        </Button>
      </div>
    </header>
  );
}
