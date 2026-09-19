import { useState } from 'react';
import { Button } from 'ui';
import { api, type SkuStockRow } from '@/lib/api';
import { filterSkuStock, type StockFilter } from '../filters';

interface Props {
  skus: SkuStockRow[];
  onMsg: (m: string) => void;
  onChanged: () => void;
}

const FILTERS: Array<{ key: StockFilter; label: string }> = [
  { key: 'ALL', label: '全部' },
  { key: 'low', label: '低库存(<50)' },
  { key: 'normal', label: '正常' },
];

/** SKU 库存总表:库存筛选 + 关键词搜索 + 行内改价/改库存(库存视角页;
 *  SKU 结构性增删仍在「商品列表」的展开子表)。 */
export function SkuStockTable({ skus, onMsg, onChanged }: Props) {
  const [filter, setFilter] = useState<StockFilter>('ALL');
  const [query, setQuery] = useState('');
  const [editing, setEditing] = useState<{ id: string; price: string; stock: string } | null>(null);

  const rows = filterSkuStock(skus, filter, query);

  async function save() {
    if (!editing) return;
    const b = await api.products.updateSku(editing.id, { price: Number(editing.price), stock: Number(editing.stock) });
    onMsg(b.success ? '✓ SKU 已保存' : `失败:${b.message}`);
    setEditing(null);
    if (b.success) onChanged();
  }

  return (
    <div className="overflow-hidden rounded-xl border border-zinc-200 bg-white">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-zinc-100 bg-zinc-50/70 px-4 py-3 text-xs">
        <div className="flex rounded-lg bg-zinc-200/80 p-0.5 font-semibold">
          {FILTERS.map((f) => (
            <button
              type="button"
              key={f.key}
              onClick={() => setFilter(f.key)}
              className={`cursor-pointer rounded-md px-3 py-1 transition ${
                filter === f.key ? 'bg-white text-zinc-900 shadow-xs' : 'text-zinc-600 hover:text-zinc-900'
              }`}
            >
              {f.label}
            </button>
          ))}
        </div>
        <input
          className="w-56 rounded-lg border border-zinc-300 px-3 py-1.5"
          placeholder="搜索 SKU 编码 / 名称 / 商品"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
      </div>

      <table className="w-full text-[13px]">
        <thead>
          <tr className="border-b border-zinc-100 text-left text-zinc-400">
            <th className="px-4 py-2 font-medium">SKU 编码</th>
            <th className="px-4 py-2 font-medium">名称</th>
            <th className="px-4 py-2 font-medium">所属商品</th>
            <th className="px-4 py-2 font-medium">价格</th>
            <th className="px-4 py-2 font-medium">库存</th>
            <th className="px-4 py-2 font-medium">操作</th>
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 && (
            <tr><td colSpan={6} className="px-4 py-6 text-center text-xs text-zinc-400">暂无匹配 SKU(诚实空)</td></tr>
          )}
          {rows.map((k) => (
            <tr key={k.id} className="border-b border-zinc-50">
              <td className="px-4 py-2 font-mono">{k.sku_code}</td>
              <td className="px-4 py-2">{k.sku_title || '—'}</td>
              <td className="px-4 py-2">{k.spu_title}</td>
              <td className="px-4 py-2">
                {editing?.id === k.id ? (
                  <input className="w-20 rounded border border-zinc-300 px-2 py-1" placeholder="价格" value={editing.price} onChange={(e) => setEditing({ ...editing, price: e.target.value })} />
                ) : (
                  `¥${k.price}`
                )}
              </td>
              <td className="px-4 py-2">
                {editing?.id === k.id ? (
                  <input className="w-16 rounded border border-zinc-300 px-2 py-1" placeholder="库存" value={editing.stock} onChange={(e) => setEditing({ ...editing, stock: e.target.value })} />
                ) : (
                  <span className={k.stock < 50 ? 'font-semibold text-rose-600' : ''}>{k.stock}</span>
                )}
              </td>
              <td className="px-4 py-2">
                {editing?.id === k.id ? (
                  <Button size="sm" onClick={() => void save()}>保存</Button>
                ) : (
                  <Button size="sm" variant="ghost" onClick={() => setEditing({ id: k.id, price: String(k.price), stock: String(k.stock) })}>改价/库存</Button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
