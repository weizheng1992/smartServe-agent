import { ApprovalContextDrawer } from 'ui';
import { ApprovalsTab } from './components/approvals-tab';
import { LiveDeskTab } from './components/live-desk-tab';
import { OrderDetailDrawer } from './components/order-detail-drawer';
import { OrdersTab } from './components/orders-tab';
import { PayloadDialog } from './components/payload-dialog';
import { RejectDialog } from './components/reject-dialog';
import { ShipDialog } from './components/ship-dialog';
import { SpiLogsTab } from './components/spi-logs-tab';
import { WorkbenchProvider, type WorkbenchScope, useWorkbench, useWorkbenchState } from './workbench';

export type { WorkbenchScope };

export default function OrderWorkbench({ scope = 'orders' }: { scope?: WorkbenchScope }) {
  const w = useWorkbenchState(scope);
  return (
    <WorkbenchProvider value={w}>
      <WorkbenchShell scope={scope} />
    </WorkbenchProvider>
  );
}

/** 薄壳:按 scope 渲染对应功能域与对应弹窗(候选⑤:死 chrome 不常挂 ——
 *  此前五个弹窗/抽屉全 scope 常驻,/spi-logs 也挂着永远打不开的 ShipDialog)。 */
function WorkbenchShell({ scope }: { scope: WorkbenchScope }) {
  const { inspectingApproval, setInspectingApproval, handleApprovalAction, handleHumanReply } = useWorkbench();

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

      {/* 审核上下文抽屉(仅审批/聊天两域可达) */}
      {(scope === 'approvals' || scope === 'live-desk') && (
        <ApprovalContextDrawer
          isOpen={Boolean(inspectingApproval)}
          onClose={() => setInspectingApproval(null)}
          approval={inspectingApproval as any}
          onApprove={async (id) => {
            await handleApprovalAction(id, 'approve');
          }}
          onReject={async (id, reason) => {
            // 驳回原因直传 explicitReason(工单 04 同病灶的抽屉版收口,快修五连)
            await handleApprovalAction(id, 'reject', reason);
          }}
          onHumanReply={async (id, replyMsg, isFinish) => {
            await handleHumanReply(id, replyMsg, isFinish);
          }}
        />
      )}
      {(scope === 'approvals' || scope === 'live-desk') && <RejectDialog />}

      {scope === 'orders' && (
        <>
          <ShipDialog />
          <OrderDetailDrawer />
        </>
      )}
      {scope === 'spi-logs' && <PayloadDialog />}
    </div>
  );
}
