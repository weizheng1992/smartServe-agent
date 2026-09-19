import { Fragment, useState } from 'react';
import { Button } from 'ui';
import { api, type Spu } from '@/lib/api';
import { SkuSubTable } from './sku-subtable';

interface Props {
  spus: Spu[];
  onMsg: (m: string) => void;
  onChanged: () => void;
}

/** SPU 列表:行内编辑(标题/售价/库存)、上/下架、删除(订单引用护栏在服务端)、
 *  展开 SKU 子表。展开态/行编辑态为本组件局部状态。 */
export function SpuTable({ spus, onMsg, onChanged }: Props) {
  const [editing, setEditing] = useState<string | null>(null);
  const [edit, setEdit] = useState({ title: '', price: '', stock: '' });
  const [openSkus, setOpenSkus] = useState<string | null>(null);

  async function saveEdit(id: string) {
    const b = await api.products.update(id, { title: edit.title, price: Number(edit.price), stock: Number(edit.stock) });
    onMsg(b.success ? '✓ 已保存' : `失败:${b.message}`);
    setEditing(null);
    if (b.success) onChanged();
  }

  async function toggleStatus(s: Spu) {
    const res = await api.products.update(s.id, { status: s.status === 'ON_SALE' ? 'OFF_SALE' : 'ON_SALE' });
    onMsg(res.success ? `✓ 「${s.title}」已${s.status === 'ON_SALE' ? '下架' : '上架'}` : '操作失败');
    onChanged();
  }

  async function remove(s: Spu) {
    const b = await api.products.remove(s.id);
    onMsg(b.success ? `✓ 已删除「${s.title}」` : `失败:${b.message}`);
    onChanged();
  }

  function toggleSkus(s: Spu) {
    setOpenSkus(openSkus === s.id ? null : s.id);
  }

  return (
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
            <Fragment key={s.id}>
              <tr className="border-b border-zinc-50">
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
                    <SkuSubTable spu={s} onMsg={onMsg} />
                  </td>
                </tr>
              )}
            </Fragment>
          ))}
        </tbody>
      </table>
    </div>
  );
}
