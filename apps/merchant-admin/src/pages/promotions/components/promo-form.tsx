import { useState } from 'react';
import { Button } from 'ui';
import { api } from '@/lib/api';

interface Props {
  msg: string;
  onMsg: (m: string) => void;
  onCreated: () => void;
}

/** 新建活动(满减/折扣/券;门槛仅满减需要)。 */
export function PromoCreateForm({ msg, onMsg, onCreated }: Props) {
  const [form, setForm] = useState({ name: '', promoType: 'full_reduction', threshold: '', value: '' });

  async function create() {
    const b = await api.promotions.create({
      name: form.name,
      promoType: form.promoType,
      threshold: form.threshold ? Number(form.threshold) : undefined,
      value: Number(form.value),
    });
    onMsg(b.success ? `✓ 已创建「${b.name}」` : `失败:${b.message}`);
    if (b.success) {
      setForm({ name: '', promoType: 'full_reduction', threshold: '', value: '' });
      onCreated();
    }
  }

  return (
    <div className="rounded-xl border border-zinc-200 bg-white p-4">
      <div className="text-sm font-medium">新建活动</div>
      <div className="mt-3 flex flex-wrap items-center gap-2 text-xs">
        <input className="w-40 rounded-lg border border-zinc-300 px-3 py-2" placeholder="活动名称" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
        <select className="rounded-lg border border-zinc-300 px-3 py-2" value={form.promoType} onChange={(e) => setForm({ ...form, promoType: e.target.value })}>
          <option value="full_reduction">满减</option>
          <option value="discount">折扣</option>
          <option value="coupon">券</option>
        </select>
        {form.promoType === 'full_reduction' && (
          <input className="w-28 rounded-lg border border-zinc-300 px-3 py-2" placeholder="门槛 ¥" value={form.threshold} onChange={(e) => setForm({ ...form, threshold: e.target.value })} />
        )}
        <input className="w-28 rounded-lg border border-zinc-300 px-3 py-2" placeholder={form.promoType === 'discount' ? '折扣(85=8.5折)' : '优惠 ¥'} value={form.value} onChange={(e) => setForm({ ...form, value: e.target.value })} />
        <Button size="sm" disabled={!form.name || !form.value} onClick={() => void create()}>创建</Button>
        {msg && <span className="text-[11px] text-zinc-400">{msg}</span>}
      </div>
      <div className="mt-2 text-[11px] text-zinc-400">
        注:下单结算自动应用优惠属资金口径改动(20-D3),经独立评审后接入;当前为活动管理与效果速览。
      </div>
    </div>
  );
}
