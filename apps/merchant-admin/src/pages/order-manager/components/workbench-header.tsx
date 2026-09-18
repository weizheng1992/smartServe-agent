import { Button } from "ui";
import { useWorkbench } from "../workbench";

/** 工作台内嵌顶栏(独立运行语义:刷新 + 返回商城前台)。 */
export function WorkbenchHeader() {
  const { fetchDashboardData } = useWorkbench();
  return (
    <header className="bg-slate-900 text-white border-b border-slate-800 h-16 flex items-center justify-between px-6 sticky top-0 z-20">
      <div className="flex items-center space-x-3">
        <div className="w-8 h-8 rounded bg-emerald-600 flex items-center justify-center font-bold text-white shadow-xs">
          A
        </div>
        <div>
          <div className="font-bold text-base tracking-tight flex items-center space-x-2">
            <span>极光潮品商户后台管理系统</span>
            <span className="text-[10px] bg-emerald-950 text-emerald-300 border border-emerald-800 px-2 py-0.5 rounded font-mono">
              Aurora Merchant Port 3005
            </span>
          </div>
          <div className="text-[11px] text-slate-400">
            独立物理隔离 · SPU/SKU 多规格电商 · HITL 审批中枢 · LiveDesk 在线客服
          </div>
        </div>
      </div>

      <div className="flex items-center space-x-4 text-xs">
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={fetchDashboardData}
          className="bg-slate-800 hover:bg-slate-700 text-slate-200 border-slate-700 h-8 cursor-pointer"
        >
          <span>🔄 刷新数据</span>
        </Button>
        <a
          href="/"
          className="px-3 py-1.5 bg-emerald-600 hover:bg-emerald-500 text-white font-medium rounded transition flex items-center space-x-1 shadow-xs cursor-pointer"
        >
          <span>🛍️ 返回商城前台</span>
        </a>
      </div>
    </header>
  );
}
