import { type Promotion, api } from '@/lib/api';
import { useState } from 'react';
import { Button, Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle, Input, Label } from 'ui';

interface Props {
  promo: Promotion;
  onClose: () => void;
  /** 核销结果消息(成功后由本组件先 onClose) */
  onDone: (msg: string) => void;
}

/** 核销弹窗:订单号 → 服务端按活动规则×订单实付计算优惠额;同订单×同活动幂等。 */
export function RedeemDialog({ promo, onClose, onDone }: Props) {
  const [orderId, setOrderId] = useState('');

  async function submitRedeem() {
    const b = await api.promotions.redeem(promo.id, orderId);
    onDone(b.success ? `✓ 已核销:订单 ${b.orderId} 优惠 ¥${b.discount}` : `失败:${b.error || b.message}`);
    if (b.success) onClose();
  }

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-sm rounded-xl border-zinc-200 text-zinc-900 shadow-xl">
        <DialogHeader className="pb-3 border-b border-zinc-100">
          <DialogTitle className="text-base font-bold text-zinc-900">核销「{promo.name}」</DialogTitle>
          <p className="mt-1 text-xs text-zinc-500">优惠额由服务端按活动规则×订单实付计算;同订单×同活动幂等</p>
        </DialogHeader>
        <div className="min-h-0 flex-1 space-y-3 overflow-y-auto py-4 text-xs">
          <div>
            <Label htmlFor="redeem-order" className="mb-1.5 block text-zinc-700">
              订单号
            </Label>
            <Input
              id="redeem-order"
              className="h-auto w-full rounded-lg border-zinc-300 px-3 py-2 shadow-none focus-visible:ring-0"
              placeholder="订单号,如 AURORA-ORD-2026-9091"
              value={orderId}
              onChange={(e) => setOrderId(e.target.value)}
            />
          </div>
        </div>
        <DialogFooter className="gap-2 pt-3 sm:gap-0 border-t border-zinc-100">
          <Button type="button" variant="outline" size="sm" onClick={onClose} className="text-xs cursor-pointer">
            取消
          </Button>
          <Button
            type="button"
            size="sm"
            disabled={!orderId}
            onClick={() => void submitRedeem()}
            className="text-xs font-bold cursor-pointer"
          >
            确认核销
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
