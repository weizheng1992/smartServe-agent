import { useCallback, useEffect, useState } from 'react';
import { Button } from 'ui';

interface Spu {
  id: string;
  spu_code: string;
  title: string;
  category: string;
  status: string;
  price: number;
  stock: number;
}

const CATEGORIES = ['户外机能', '潮流T恤', '下装裤类', '潮流鞋靴', '背包收纳', '露营装备', '衬衫', '配饰', '运动配件'];
const H = () => ({
  'Content-Type': 'application/json',
  'x-tenant-id': 'aurora',
  'x-user-id': localStorage.getItem('merchant-admin.staff') || 'boss@aurora',
  Authorization: `Bearer ${localStorage.getItem('merchant-admin.token') || ''}`,
});

// 商品目录管理(增删改查;删除受订单引用护栏,有成交只可下架)
export default function ProductsPage() {
  const [spus, setSpus] = useState<Spu[]>([]);
  const [msg, setMsg] = useState('');
  const [form, setForm] = useState<{ open: boolean; id?: string; title: string; category: string; price: string; stock: string }>({ open: false, title: '', category: CATEGORIES[0], price: '', stock: '10' });
  const [editing, setEditing] = useState<string | null>(null);
  const [edit, setEdit] = useState({ title: '', price: '', stock: '' });

  const load = useCallback(async () => {
    const res = await fetch('/api/admin/analytics/spus', { headers: H() });
    setSpus((await res.json()).spus || []);
  }, []);
  useEffect(() => { void load(); }, [load]);

  async function create() {
    const res = await fetch('/api/admin/analytics/spus', { method: 'POST', headers: H(), body: JSON.stringify({ title: form.title, category: form.category, price: Number(form.price), stock: Number(form.stock) }) });
    const b = await res.json();
    setMsg(b.success ? `✓ 已上架「${form.title}」(${b.spuCode})` : `失败:${b.message}`);
    if (b.success) { setForm({ ...form, open: false, title: '', price: '' }); void load(); }
  }
  async function saveEdit(id: string) {
    const res = await fetch(`/api/admin/analytics/spus/${id}`, { method: 'PATCH', headers: H(), body: JSON.stringify({ title: edit.title, price: Number(edit.price), stock: Number(edit.stock) }) });
    const b = await res.json();
    setMsg(b.success ? '✓ 已保存' : `失败:${b.message}`);
    setEditing(null);
    if (b.success) void load();
  }
  async function toggleStatus(s: Spu) {
    const res = await fetch(`/api/admin/analytics/spus/${s.id}`, { method: 'PATCH', headers: H(), body: JSON.stringify({ status: s.status === 'ON_SALE' ? 'OFF_SALE' : 'ON_SALE' }) });
    setMsg(res.ok ? `✓ 「${s.title}」已${s.status === 'ON_SALE' ? '下架' : '上架'}` : '操作失败');
    void load();
  }
  async function remove(s: Spu) {
    const res = await fetch(`/api/admin/analytics/spus/${s.id}`, { method: 'DELETE', headers: H() });
    const b = await res.json();
    setMsg(b.success ? `✓ 已删除「${s.title}」` : `失败:${b.message}`);
    void load();
  }

  return (
    <div className="mx-auto max-w-5xl space-y-4">
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

      <div className="overflow-hidden rounded-xl border border-zinc-200 bg-white">
        <table className="w-full text-[13px]">
          <thead>
            <tr className="border-b border-zinc-100 text-left text-zinc-400">
              <th className="px-4 py-2 font-medium">商品</th>
              <th className="px-4 py-2 font-medium">品类</th>
              <th className="px-4 py-2 font-medium">售价</th>
              <th className="px-4 py-2 font-medium">库存</th>
              <th className="px-4 py-2 font-medium">状态</th>
              <th className="px-4 py-2 font-medium">操作</th>
            </tr>
          </thead>
          <tbody>
            {spus.map((s) => (
              <tr key={s.id} className="border-b border-zinc-50">
                <td className="px-4 py-2">
                  {editing === s.id ? (
                    <input className="w-64 rounded border border-zinc-300 px-2 py-1" value={edit.title} onChange={(e) => setEdit({ ...edit, title: e.target.value })} />
                  ) : (
                    s.title
                  )}
                </td>
                <td className="px-4 py-2">{s.category}</td>
                <td className="px-4 py-2">
                  {editing === s.id ? (
                    <input className="w-20 rounded border border-zinc-300 px-2 py-1" value={edit.price} onChange={(e) => setEdit({ ...edit, price: e.target.value })} />
                  ) : (
                    `¥${s.price}`
                  )}
                </td>
                <td className="px-4 py-2">
                  {editing === s.id ? (
                    <input className="w-16 rounded border border-zinc-300 px-2 py-1" value={edit.stock} onChange={(e) => setEdit({ ...edit, stock: e.target.value })} />
                  ) : (
                    s.stock
                  )}
                </td>
                <td className="px-4 py-2">
                  <span className={s.status === 'ON_SALE' ? 'text-emerald-600' : 'text-zinc-400'}>{s.status === 'ON_SALE' ? '在售' : '下架'}</span>
                </td>
                <td className="px-4 py-2">
                  {editing === s.id ? (
                    <Button size="sm" onClick={() => void saveEdit(s.id)}>保存</Button>
                  ) : (
                    <div className="flex gap-1">
                      <Button size="sm" variant="ghost" onClick={() => { setEditing(s.id); setEdit({ title: s.title, price: String(s.price), stock: String(s.stock) }); }}>编辑</Button>
                      <Button size="sm" variant="ghost" onClick={() => void toggleStatus(s)}>{s.status === 'ON_SALE' ? '下架' : '上架'}</Button>
                      <Button size="sm" variant="ghost" className="text-rose-600" onClick={() => void remove(s)}>删除</Button>
                    </div>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
