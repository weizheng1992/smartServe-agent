import { useEffect, useState } from 'react';
import { Button } from 'ui';
import { api, type Spu } from '@/lib/api';
import { scopeEditableFor } from './scope';

interface Props {
  msg: string;
  onMsg: (m: string) => void;
  onCreated: () => void;
}

const EMPTY = { name: '', promoType: 'full_reduction', threshold: '', value: '', scopeType: 'all', scopeValue: '' };

/** 新建活动:满减/折扣可选适用范围(全部/指定商品);券型无范围(引擎语义)。 */
export function PromoCreateForm({ msg, onMsg, onCreated }: Props) {
  const [form, setForm] = useState(EMPTY);
  const [spus, setSpus] = useState<Spu[]>([]);

  useEffect(() => { void api.products.list().then((b) => setSpus(b.spus || [])); }, []);

  async function create() {
    const b = await api.promotions.create({
      name: form.name,
      promoType: form.promoType,
      threshold: form.threshold ? Number(form.threshold) : undefined,
      value: Number(form.value),
      scopeType: form.scopeType,
      scopeValue: form.scopeType === 'spu' ? form.scopeValue : undefined,
    });
    onMsg(b.success ? `✓ 已创建「${b.name}」` : `失败:${b.message}`);
    if (b.success) {
      setForm(EMPTY);
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
        {scopeEditableFor(form.promoType) && (
          <>
            <select className="rounded-lg border border-zinc-300 px-3 py-2" value={form.scopeType} onChange={(e) => setForm({ ...form, scopeType: e.target.value, scopeValue: '' })}>
              <option value="all">全部商品</option>
              <option value="spu">指定商品</option>
            </select>
            {form.scopeType === 'spu' && (
              <select className="w-48 rounded-lg border border-zinc-300 px-3 py-2" value={form.scopeValue} onChange={(e) => setForm({ ...form, scopeValue: e.target.value })}>
                <option value="">选择商品…</option>
                {spus.map((s) => <option key={s.id} value={s.spu_code}>{s.title}({s.spu_code})</option>)}
              </select>
            )}
          </>
        )}
        <Button size="sm" disabled={!form.name || !form.value || (form.scopeType === 'spu' && !form.scopeValue)} onClick={() => void create()}>创建</Button>
        {msg && <span className="text-[11px] text-zinc-400">{msg}</span>}
      </div>
      <div className="mt-2 text-[11px] text-zinc-400">
        注:指定商品范围当前仅满减/折扣生效,优惠按整单金额计算;券型活动全员可领可用(引擎口径);下单结算自动应用属资金口径(20-D3)。
      </div>
    </div>
  );
}
