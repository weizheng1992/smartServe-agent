import { FormDialogShell } from '@/components/form-dialog-shell';
import { CARRIER_OPTIONS } from '@/lib/format';
import { Input, Label, Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from 'ui';
import { useWorkbench } from '../workbench';

/** 订单一键发货弹窗(承运商 + 运单号;提交后锁定收货地址)。
 *  收编 FormDialogShell(2026-10-31 盲区清偿):chrome/busy 防重复提交/错误留窗
 *  走壳;handleShipOrder 按壳契约返回失败文案(null=成功壳自关)。 */
export function ShipDialog() {
  const {
    shippingOrderId,
    setShippingOrderId,
    carrierInput,
    setCarrierInput,
    trackingNumberInput,
    setTrackingNumberInput,
    handleShipOrder,
  } = useWorkbench();

  if (!shippingOrderId) return null;

  return (
    <FormDialogShell
      title="订单一键发货"
      subtitle={<span className="font-mono">订单号: {shippingOrderId}</span>}
      maxWidth="max-w-sm"
      submitLabel="确认发货并锁定地址"
      submitDisabled={!trackingNumberInput.trim()}
      onClose={() => setShippingOrderId(null)}
      onSubmit={async () => handleShipOrder(shippingOrderId)}
    >
      <div>
        <Label htmlFor="ship-carrier" className="mb-1 block text-xs font-semibold text-zinc-700">
          承运快递公司
        </Label>
        {/* ui Select(Radix):受控 value/onValueChange;Label htmlFor 关联 trigger 内部按钮 */}
        <Select value={carrierInput} onValueChange={(v) => setCarrierInput(v)}>
          <SelectTrigger
            id="ship-carrier"
            aria-label="承运快递公司"
            className="w-full rounded-lg border-zinc-300 px-3 py-2 text-xs"
          >
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {CARRIER_OPTIONS.map((c) => (
              <SelectItem key={c.code} value={c.code}>
                {c.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div>
        <Label htmlFor="ship-tracking" className="mb-1 block text-xs font-semibold text-zinc-700">
          快递运单号
        </Label>
        <Input
          id="ship-tracking"
          type="text"
          value={trackingNumberInput}
          onChange={(e) => setTrackingNumberInput(e.target.value)}
          className="text-xs h-9 bg-white font-mono"
          placeholder="请输入运单号..."
        />
      </div>
    </FormDialogShell>
  );
}
