import { useCallback, useEffect, useState } from 'react';
import { Button } from 'ui';

interface Sku {
  id: string;
  sku_code: string;
  sku_title: string | null;
  price: number;
  stock: number;
  spec_attributes: string | null;
}

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
  const [openSkus, setOpenSkus] = useState<string | null>(null);
  const [skus, setSkus] = useState<Sku[]>([]);
  const [newSku, setNewSku] = useState<{ skuTitle: string; price: string; stock: string }>({ skuTitle: '', price: '', stock: '' });
  const [skuEdit, setSkuEdit] = useState<{ id: string; price: string; stock: string } | null>(null);

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
  async function loadSkus(spuId: string) {
    const res = await fetch(`/api/admin/analytics/spus/${spuId}/skus`, { headers: H() });
    setSkus((await res.json()).skus || []);
  }
  function toggleSkus(s: Spu) {
    if (openSkus === s.id) { setOpenSkus(null); return; }
    setOpenSkus(s.id);
    void loadSkus(s.id);
  }
  async function createSku(spuId: string) {
    const res = await fetch(`/api/admin/analytics/spus/${spuId}/skus`, { method: 'POST', headers: H(), body: JSON.stringify(newSku) });
    const b = await res.json();
    setMsg(b.success ? `✓ SKU ${b.skuCode} 已新增` : `失败:${b.message}`);
    if (b.success) { setNewSku({ skuTitle: '', price: '', stock: '' }); void loadSkus(spuId); }
  }
  async function saveSku(skuId: string, spuId: string, patch: { price: string; stock: string }) {
    const res = await fetch(`/api/admin/analytics/skus/${skuId}`, {
      method: 'PATCH', headers: H(),
      body: JSON.stringify({ price: Number(patch.price), stock: Number(patch.stock) }),
    });
    setMsg(res.ok ? '✓ SKU 已保存' : '保存失败');
    void loadSkus(spuId);
  }
  async function deleteSku(skuId: string, spuId: string) {
    const res = await fetch(`/api/admin/analytics/skus/${skuId}`, { method: 'DELETE', headers: H() });
    const b = await res.json();
    setMsg(b.success ? '✓ 已删除' : `失败:${b.message}`);
    void loadSkus(spuId);
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
              <>
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
                      <Button size="sm" variant="ghost" onClick={() => toggleSkus(s)}>SKU</Button>
                      <Button size="sm" variant="ghost" className="text-rose-600" onClick={() => void remove(s)}>删除</Button>
                    </div>
                  )}
                </td>
              </tr>
              {openSkus === s.id && (
                <tr className="bg-zinc-50/60">
                  <td colSpan={6} className="px-6 py-3">
                    <div className="text-[11px] font-semibold text-zinc-500 mb-2">SKU 明细 · {s.spu_code}</div>
                    <table className="w-full text-[12px]">
                      <thead><tr className="text-left text-zinc-400">
                        <th className="py-1 pr-4 font-medium">SKU 编码</th><th className="py-1 pr-4 font-medium">价格</th>
                        <th className="py-1 pr-4 font-medium">库存</th><th className="py-1 font-medium">操作</th>
                      </tr></thead>
                      <tbody>
                        {skus.map((k) => (
                          <tr key={k.id}>
                            <td className="py-1 pr-4 font-mono">{k.sku_code}</td>
                            <td className="py-1 pr-4">¥{k.price}</td>
                            <td className="py-1 pr-4">{k.stock}</td>
                            <td className="py-1">
                              <Button size="sm" variant="ghost" onClick={() => setSkuEdit({ id: k.id, price: String(k.price), stock: String(k.stock) })}>改价/库存</Button>
                              <Button size="sm" variant="ghost" className="text-rose-600" onClick={() => void deleteSku(k.id, s.id)}>删除</Button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                    {skuEdit && (
                      <div className="mt-2 flex items-center gap-2 text-xs">
                        <span className="text-zinc-500">改价/库存:</span>
                        <input className="w-24 rounded border border-zinc-300 px-2 py-1" placeholder="价格" value={skuEdit.price} onChange={(e) => setSkuEdit({ ...skuEdit, price: e.target.value })} />
                        <input className="w-20 rounded border border-zinc-300 px-2 py-1" placeholder="库存" value={skuEdit.stock} onChange={(e) => setSkuEdit({ ...skuEdit, stock: e.target.value })} />
                        <Button size="sm" onClick={() => skuEdit && void saveSku(skuEdit.id, s.id, skuEdit)}>保存</Button>
                      </div>
                    )}
                    <div className="mt-2 flex items-center gap-2 text-xs">
                      <input className="w-32 rounded border border-zinc-300 px-2 py-1" placeholder="新 SKU 标题" value={newSku.skuTitle} onChange={(e) => setNewSku({ ...newSku, skuTitle: e.target.value })} />
                      <input className="w-24 rounded border border-zinc-300 px-2 py-1" placeholder="价格" value={newSku.price} onChange={(e) => setNewSku({ ...newSku, price: e.target.value })} />
                      <input className="w-20 rounded border border-zinc-300 px-2 py-1" placeholder="库存" value={newSku.stock} onChange={(e) => setNewSku({ ...newSku, stock: e.target.value })} />
                      <Button size="sm" variant="outline" disabled={!newSku.price} onClick={() => void createSku(s.id)}>新增 SKU</Button>
                    </div>
                  </td>
                </tr>
              )}
              </>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
