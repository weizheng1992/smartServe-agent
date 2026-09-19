import { useState } from 'react';
import { Button } from 'ui';
import { api } from '@/lib/api';

export const CATEGORIES = ['户外机能', '潮流T恤', '下装裤类', '潮流鞋靴', '背包收纳', '露营装备', '衬衫', '配饰', '运动配件'];

interface Props {
  msg: string;
  onMsg: (m: string) => void;
  onCreated: () => void;
}

/** 新增商品(上架即建 SPU + 默认 SKU)。 */
export function SpuCreateForm({ msg, onMsg, onCreated }: Props) {
  const [form, setForm] = useState({ title: '', category: CATEGORIES[0], price: '', stock: '10' });

  async function create() {
    const b = await api.products.create({
      title: form.title, category: form.category, price: Number(form.price), stock: Number(form.stock),
    });
    onMsg(b.success ? `✓ 已上架「${form.title}」(${b.spuCode})` : `失败:${b.message}`);
    if (b.success) {
      setForm({ ...form, title: '', price: '' });
      onCreated();
    }
  }

  return (
    <div className="rounded-xl border border-zinc-200 bg-white p-4">
      <div className="text-sm font-medium">新增商品</div>
      <div className="mt-3 flex flex-wrap items-center gap-2 text-xs">
        <input className="w-56 rounded-lg border border-zinc-300 px-3 py-2" placeholder="商品标题" value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} />
        <select className="rounded-lg border border-zinc-300 px-3 py-2" value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })}>
          {CATEGORIES.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
        <input className="w-28 rounded-lg border border-zinc-300 px-3 py-2" placeholder="售价 ¥" value={form.price} onChange={(e) => setForm({ ...form, price: e.target.value })} />
        <input className="w-24 rounded-lg border border-zinc-300 px-3 py-2" placeholder="库存" value={form.stock} onChange={(e) => setForm({ ...form, stock: e.target.value })} />
        <Button size="sm" disabled={!form.title || !form.price} onClick={() => void create()}>上架</Button>
        {msg && <span className="text-[11px] text-zinc-400">{msg}</span>}
      </div>
    </div>
  );
}
