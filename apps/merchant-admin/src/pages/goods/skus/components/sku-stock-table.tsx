import {
  DenseTable,
  DenseTableBody,
  DenseTableCell,
  DenseTableHead,
  DenseTableHeader,
  DenseTableRow,
} from '@/components/dense-table';
import { type SkuStockRow, api } from '@/lib/api';
import { useState } from 'react';
import { Button, Input } from 'ui';
import { type StockFilter, filterSkuStock } from '../filters';

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
            <Button
              type="button"
              variant="ghost"
              key={f.key}
              onClick={() => setFilter(f.key)}
              className={`h-auto cursor-pointer rounded-md px-3 py-1 text-xs font-semibold transition ${
                filter === f.key
                  ? 'bg-white text-zinc-900 shadow-xs hover:bg-white hover:text-zinc-900'
                  : 'text-zinc-600 hover:bg-transparent hover:text-zinc-900'
              }`}
            >
              {f.label}
            </Button>
          ))}
        </div>
        <Input
          className="h-auto w-56 rounded-lg border-zinc-300 px-3 py-1.5 text-xs shadow-none focus-visible:ring-0"
          placeholder="搜索 SKU 编码 / 名称 / 商品"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
      </div>

      <DenseTable>
        <DenseTableHeader>
          <DenseTableRow className="border-b border-zinc-100 hover:bg-transparent">
            <DenseTableHead>SKU 编码</DenseTableHead>
            <DenseTableHead>名称</DenseTableHead>
            <DenseTableHead>所属商品</DenseTableHead>
            <DenseTableHead>价格</DenseTableHead>
            <DenseTableHead>库存</DenseTableHead>
            <DenseTableHead>操作</DenseTableHead>
          </DenseTableRow>
        </DenseTableHeader>
        <DenseTableBody>
          {rows.length === 0 && (
            <DenseTableRow>
              <DenseTableCell colSpan={6} className="py-6 text-center text-xs text-zinc-400">
                暂无匹配 SKU(诚实空)
              </DenseTableCell>
            </DenseTableRow>
          )}
          {rows.map((k) => (
            <DenseTableRow key={k.id}>
              <DenseTableCell className="font-mono">{k.sku_code}</DenseTableCell>
              <DenseTableCell>{k.sku_title || '—'}</DenseTableCell>
              <DenseTableCell>{k.spu_title}</DenseTableCell>
              <DenseTableCell>
                {editing?.id === k.id ? (
                  <Input
                    className="h-auto w-20 rounded border-zinc-300 px-2 py-1 text-xs shadow-none focus-visible:ring-0"
                    placeholder="价格"
                    value={editing.price}
                    onChange={(e) => setEditing({ ...editing, price: e.target.value })}
                  />
                ) : (
                  `¥${k.price}`
                )}
              </DenseTableCell>
              <DenseTableCell>
                {editing?.id === k.id ? (
                  <Input
                    className="h-auto w-16 rounded border-zinc-300 px-2 py-1 text-xs shadow-none focus-visible:ring-0"
                    placeholder="库存"
                    value={editing.stock}
                    onChange={(e) => setEditing({ ...editing, stock: e.target.value })}
                  />
                ) : (
                  <span className={k.stock < 50 ? 'font-semibold text-rose-600' : ''}>{k.stock}</span>
                )}
              </DenseTableCell>
              <DenseTableCell>
                {editing?.id === k.id ? (
                  <Button size="sm" onClick={() => void save()}>
                    保存
                  </Button>
                ) : (
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => setEditing({ id: k.id, price: String(k.price), stock: String(k.stock) })}
                  >
                    改价/库存
                  </Button>
                )}
              </DenseTableCell>
            </DenseTableRow>
          ))}
        </DenseTableBody>
      </DenseTable>
    </div>
  );
}
