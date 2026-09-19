import { ApprovalContextDrawer } from "ui";
import { useWorkbench, useWorkbenchState, WorkbenchProvider } from "./workbench";
import { OrdersTab } from './components/orders-tab';
import { ApprovalsTab } from './components/approvals-tab';
import { LiveDeskTab } from './components/live-desk-tab';
import { SpiLogsTab } from './components/spi-logs-tab';
import { ShipDialog } from './components/ship-dialog';
import { RejectDialog } from './components/reject-dialog';
import { PayloadDialog } from './components/payload-dialog';

/** 工作台范围(与菜单一一对应,各渲染各的):
 *  orders=订单列表;approvals=纯待办审核;live-desk=在线聊天+待办审核;spi-logs=审计流水。 */
export type WorkbenchScope = 'orders' | 'approvals' | 'live-desk' | 'spi-logs';

const PRIMARY_TAB: Record<WorkbenchScope, string> = {
  orders: 'orders', approvals: 'approvals', 'live-desk': 'live_desk', 'spi-logs': 'spi_logs',
};

export default function OrderWorkbench({ scope = 'orders' }: { scope?: WorkbenchScope }) {
  const w = useWorkbenchState(PRIMARY_TAB[scope]);
  return (
    <WorkbenchProvider value={w}>
      <WorkbenchShell scope={scope} />
    </WorkbenchProvider>
  );
}

/** 薄壳:按 scope 渲染对应功能域(数据仍共享同一轮询上下文),弹窗与抽屉常挂。 */
function WorkbenchShell({ scope }: { scope: WorkbenchScope }) {
  const { inspectingApproval, setInspectingApproval, setRejectionReasons, handleApprovalAction, handleHumanReply } =
    useWorkbench();

  return (
    <div className="min-h-screen bg-slate-100 flex flex-col font-sans">
      <div className="mx-auto w-full max-w-7xl flex-1 space-y-6 p-6">
        {scope === 'orders' && <OrdersTab />}
        {scope === 'approvals' && <ApprovalsTab />}
        {scope === 'live-desk' && (
          <>
            <LiveDeskTab />
            <ApprovalsTab />
          </>
        )}
        {scope === 'spi-logs' && <SpiLogsTab />}
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
