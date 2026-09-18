import { Button, Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle, Input } from "ui";
import { useWorkbench } from "../workbench";

/** 订单一键发货弹窗(承运商 + 运单号;提交后锁定收货地址)。 */
export function ShipDialog() {
  const {
    shippingOrderId, setShippingOrderId, carrierInput, setCarrierInput, trackingNumberInput, setTrackingNumberInput,
    handleShipOrder,
  } = useWorkbench();

  return (
    <Dialog open={Boolean(shippingOrderId)} onOpenChange={(open) => !open && setShippingOrderId(null)}>
      <DialogContent className="max-w-sm p-6 bg-white text-slate-900 border-slate-200">
        <DialogHeader className="pb-3 border-b border-slate-100">
          <DialogTitle className="text-base font-bold text-slate-900">订单一键发货</DialogTitle>
          <p className="text-xs text-slate-500 mt-1 font-mono">订单号: {shippingOrderId}</p>
        </DialogHeader>

        <div className="space-y-3 py-3">
          <div>
            <label htmlFor="ship-carrier" className="block text-xs font-semibold text-slate-700 mb-1">
              承运快递公司
            </label>
            <select
              id="ship-carrier"
              value={carrierInput}
              onChange={(e) => setCarrierInput(e.target.value)}
              className="w-full px-3 py-2 text-xs border border-slate-300 rounded-lg bg-white focus:outline-hidden focus:ring-2 focus:ring-emerald-500"
            >
              <option value="SF">顺丰速运 (SF Express)</option>
              <option value="JD">京东快递 (JD Logistics)</option>
              <option value="ZTO">中通快递 (ZTO)</option>
              <option value="EMS">邮政 EMS</option>
            </select>
          </div>

          <div>
            <label htmlFor="ship-tracking" className="block text-xs font-semibold text-slate-700 mb-1">
              快递运单号
            </label>
            <Input
              id="ship-tracking"
              type="text"
              value={trackingNumberInput}
              onChange={(e) => setTrackingNumberInput(e.target.value)}
              className="text-xs h-9 bg-white font-mono"
              placeholder="请输入运单号..."
            />
          </div>
        </div>

        <DialogFooter className="gap-2 sm:gap-0 pt-3 border-t border-slate-100">
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => setShippingOrderId(null)}
            className="text-xs cursor-pointer"
          >
            取消
          </Button>
          <Button
            type="button"
            size="sm"
            onClick={() => shippingOrderId && handleShipOrder(shippingOrderId)}
            className="bg-blue-600 hover:bg-blue-500 text-white text-xs font-bold cursor-pointer"
          >
            确认发货并锁定地址
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
