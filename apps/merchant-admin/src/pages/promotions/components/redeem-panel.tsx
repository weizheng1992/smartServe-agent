import { FormDialogShell } from '@/components/form-dialog-shell';
import { type Promotion, api, errMsgOf } from '@/lib/api';
import { useState } from 'react';
import { Input, Label } from 'ui';

interface Props {
  promo: Promotion;
  onClose: () => void;
  /** props 命名收敛:onDone → onMsg(2026-10-15 候选④)。 */
  onMsg: (msg: string) => void;
}

/** 核销弹窗:订单号 → 服务端按活动规则×订单实付计算优惠额;同订单×同活动幂等。 */
export function RedeemDialog({ promo, onClose, onMsg }: Props) {
  const [orderId, setOrderId] = useState('');

  return (
    <FormDialogShell
      title={`核销「${promo.name}」`}
      subtitle="优惠额由服务端按活动规则×订单实付计算;同订单×同活动幂等"
      submitLabel="确认核销"
      submitDisabled={!orderId}
      onClose={onClose}
      onSubmit={async () => {
        const b = await api.promotions.redeem(promo.id, orderId);
        if (!b.success) return errMsgOf(b);
        onMsg(`✓ 已核销:订单 ${b.orderId} 优惠 ¥${b.discount}`);
        return null;
      }}
    >
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
    </FormDialogShell>
  );
}
