import { type Promotion, api } from '@/lib/api';
import { useState } from 'react';
import { Button } from 'ui';

interface Props {
  promo: Promotion;
  onCancel: () => void;
  onDone: (msg: string) => void;
}

/** 核销面板:订单号 → 服务端按活动规则×订单实付计算优惠额;同订单×同活动幂等。 */
export function RedeemPanel({ promo, onCancel, onDone }: Props) {
  const [orderId, setOrderId] = useState('');

  async function submitRedeem() {
    const b = await api.promotions.redeem(promo.id, orderId);
    onDone(b.success ? `✓ 已核销:订单 ${b.orderId} 优惠 ¥${b.discount}` : `失败:${b.error || b.message}`);
    if (b.success) onCancel();
  }

  return (
    <div className="rounded-xl border border-blue-200 bg-blue-50/60 p-4">
      <div className="text-sm font-medium">核销「{promo.name}」</div>
      <div className="mt-2 flex flex-wrap items-center gap-2 text-xs">
        <input
          className="w-64 rounded-lg border border-zinc-300 px-3 py-2"
          placeholder="订单号,如 AURORA-ORD-2026-9091"
          value={orderId}
          onChange={(e) => setOrderId(e.target.value)}
        />
        <Button size="sm" disabled={!orderId} onClick={() => void submitRedeem()}>
          确认核销
        </Button>
        <Button size="sm" variant="ghost" onClick={onCancel}>
          取消
        </Button>
        <span className="text-[11px] text-zinc-400">优惠额由服务端按活动规则×订单实付计算;同订单×同活动幂等</span>
      </div>
    </div>
  );
}
