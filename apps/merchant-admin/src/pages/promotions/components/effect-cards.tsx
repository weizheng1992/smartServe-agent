import type { PromoEffect } from '@/lib/api';

/** 效果速览三卡:进行中活动 / 累计核销 / 累计优惠金额。 */
export function EffectCards({ effect }: { effect: PromoEffect | null }) {
  return (
    <div className="grid grid-cols-3 gap-3">
      <div className="rounded-xl border border-zinc-200 bg-white p-4 text-center">
        <div className="text-xl font-semibold">{effect?.activePromotions ?? '—'}</div>
        <div className="text-[11px] text-zinc-400">进行中活动</div>
      </div>
      <div className="rounded-xl border border-zinc-200 bg-white p-4 text-center">
        <div className="text-xl font-semibold">{effect?.redemptions ?? '—'}</div>
        <div className="text-[11px] text-zinc-400">累计核销单数</div>
      </div>
      <div className="rounded-xl border border-zinc-200 bg-white p-4 text-center">
        <div className="text-xl font-semibold">¥{(effect?.totalDiscount ?? 0).toLocaleString()}</div>
        <div className="text-[11px] text-zinc-400">累计优惠金额</div>
      </div>
    </div>
  );
}
