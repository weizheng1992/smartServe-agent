import { Button, Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "ui";
import { useWorkbench } from "../workbench";

/** SPI 调用结果 Payload 查看弹窗(复制 JSON)。 */
export function PayloadDialog() {
  const { selectedLog, setSelectedLog, copiedLog, setCopiedLog } = useWorkbench();

  return (
    <Dialog open={Boolean(selectedLog)} onOpenChange={(open) => !open && setSelectedLog(null)}>
      <DialogContent className="max-w-lg p-6 bg-white text-slate-900 border-slate-200">
        <DialogHeader className="pb-3 border-b border-slate-100">
          <DialogTitle className="text-sm font-bold text-slate-900 flex items-center justify-between">
            <span>SPI 调用结果 Payload</span>
            {selectedLog && (
              <span className="text-xs font-mono font-normal text-slate-500">
                {selectedLog.action_type} · {selectedLog.order_id}
              </span>
            )}
          </DialogTitle>
        </DialogHeader>

        <div className="py-3">
          <pre className="bg-slate-900 text-emerald-400 p-3.5 rounded-xl text-xs overflow-x-auto max-h-72 font-mono leading-relaxed border border-slate-800">
            {JSON.stringify(selectedLog?.payload, null, 2)}
          </pre>
        </div>

        <DialogFooter className="pt-3 border-t border-slate-100 flex items-center justify-between">
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => {
              if (selectedLog?.payload) {
                navigator.clipboard.writeText(JSON.stringify(selectedLog.payload, null, 2));
                setCopiedLog(true);
                setTimeout(() => setCopiedLog(false), 2000);
              }
            }}
            className="text-xs cursor-pointer"
          >
            {copiedLog ? '✓ 已复制 JSON' : '📋 复制 JSON'}
          </Button>
          <Button
            type="button"
            size="sm"
            onClick={() => setSelectedLog(null)}
            className="bg-slate-900 text-white text-xs font-semibold hover:bg-slate-800 cursor-pointer"
          >
            关闭
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
