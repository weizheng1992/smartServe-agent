import { ApprovalContextDrawer } from "ui";
import { useWorkbench, useWorkbenchState, WorkbenchProvider } from "./workbench";
import { WorkbenchHeader } from './components/workbench-header';
import { StatCards } from './components/stat-cards';
import { TabNav } from './components/tab-nav';
import { OrdersTab } from './components/orders-tab';
import { ApprovalsTab } from './components/approvals-tab';
import { LiveDeskTab } from './components/live-desk-tab';
import { SpusTab } from './components/spus-tab';
import { SkusTab } from './components/skus-tab';
import { SpiLogsTab } from './components/spi-logs-tab';
import { ShipDialog } from './components/ship-dialog';
import { RejectDialog } from './components/reject-dialog';
import { PayloadDialog } from './components/payload-dialog';

export default function OrderWorkbench({ initialTab = "orders" }: { initialTab?: string }) {
  const w = useWorkbenchState(initialTab);
  return (
    <WorkbenchProvider value={w}>
      <WorkbenchShell />
    </WorkbenchProvider>
  );
}

/** 工作台薄壳:纯编排(顶栏/看板/Tab 导航/六个功能域 tab/弹窗与抽屉)。
 *  各功能域的实现细节在其 components/ 下按功能拆分;非当前 tab 不渲染。 */
function WorkbenchShell() {
  const { inspectingApproval, setInspectingApproval, setRejectionReasons, handleApprovalAction, handleHumanReply } =
    useWorkbench();

  return (
    <div className="min-h-screen bg-slate-100 flex flex-col font-sans">
      <WorkbenchHeader />

      {/* 主体工作台 */}
      <div className="max-w-7xl w-full mx-auto p-6 flex-1 flex flex-col space-y-6">
        <StatCards />
        <TabNav />

        {/* 功能域 tab:各组件内部按 activeTab 自行门控 */}
        <OrdersTab />
        <ApprovalsTab />
        <LiveDeskTab />
        <SpusTab />
        <SkusTab />
        <SpiLogsTab />
      </div>

      {/* 审核上下文抽屉 */}
      <ApprovalContextDrawer
        isOpen={Boolean(inspectingApproval)}
        onClose={() => setInspectingApproval(null)}
        approval={inspectingApproval as any}
        onApprove={async (id) => {
          await handleApprovalAction(id, 'approve');
        }}
        onReject={async (id, reason) => {
          if (reason) {
            setRejectionReasons((prev) => ({ ...prev, [id]: reason }));
          }
          await handleApprovalAction(id, 'reject');
        }}
        onHumanReply={async (id, replyMsg, isFinish) => {
          await handleHumanReply(id, replyMsg, isFinish);
        }}
      />

      <ShipDialog />
      <PayloadDialog />
      <RejectDialog />
    </div>
  );
}
