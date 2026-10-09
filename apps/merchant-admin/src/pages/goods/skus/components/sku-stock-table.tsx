import {
  DenseTable,
  DenseTableBody,
  DenseTableCell,
  DenseTableHead,
  DenseTableHeader,
  DenseTableRow,
} from '@/components/dense-table';
import { type SkuStockRow, api } from '@/lib/api';
import { useEffect, useState } from 'react';
import { Button, Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle, Input, Label } from 'ui';
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
  // 改价/库存走弹窗(编辑对象即整行 Sku,预填当前值)
  const [priceEdit, setPriceEdit] = useState<SkuStockRow | null>(null);

  const rows = filterSkuStock(skus, filter, query);

  async function save() {
    if (!priceEdit) return;
    const b = await api.products.updateSku(priceEdit.id, {
      price: Number(priceEdit.price),
      stock: Number(priceEdit.stock),
    });
    onMsg(b.success ? '✓ SKU 已保存' : `失败:${b.message}`);
    if (b.success) {
      setPriceEdit(null);
      onChanged();
    }
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
              <DenseTableCell>¥{k.price}</DenseTableCell>
              <DenseTableCell>
                <span className={k.stock < 50 ? 'font-semibold text-rose-600' : ''}>{k.stock}</span>
              </DenseTableCell>
              <DenseTableCell>
                <Button size="sm" variant="ghost" onClick={() => setPriceEdit(k)}>
                  改价/库存
                </Button>
              </DenseTableCell>
            </DenseTableRow>
          ))}
        </DenseTableBody>
      </DenseTable>
      {priceEdit && (
        <PriceEditDialog
          sku={priceEdit}
          onMsg={onMsg}
          onClose={() => {
            setPriceEdit(null);
            onChanged();
          }}
        />
      )}
    </div>
  );
}

/** 改价/库存弹窗(库存视角页;保存走 api.products.updateSku,与商品列表子表同口径)。 */
function PriceEditDialog({
  sku,
  onMsg,
  onClose,
}: {
  sku: SkuStockRow;
  onMsg: (m: string) => void;
  onClose: () => void;
}) {
  const [patch, setPatch] = useState({ price: String(sku.price), stock: String(sku.stock) });
  // 价格数值未就绪不提交(防 NaN),与原行内保存同口径
  const ready = patch.price !== '' && Number.isFinite(Number(patch.price));

  async function submit() {
    if (!ready) return;
    const b = await api.products.updateSku(sku.id, { price: Number(patch.price), stock: Number(patch.stock) });
    onMsg(b.success ? '✓ SKU 已保存' : `失败:${b.message}`);
    if (b.success) onClose();
  }
  useEffect(() => {
    // sku 变化时重置预填(组件随行挂载,防御性)
    setPatch({ price: String(sku.price), stock: String(sku.stock) });
  }, [sku]);

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-sm rounded-xl border-zinc-200 text-zinc-900 shadow-xl">
        <DialogHeader className="pb-3 border-b border-zinc-100">
          <DialogTitle className="text-base font-bold text-zinc-900">改价/库存 · {sku.sku_code}</DialogTitle>
          <p className="mt-1 text-xs text-zinc-500">
            {sku.sku_title || '—'} · {sku.spu_title}
          </p>
        </DialogHeader>
        <div className="min-h-0 flex-1 space-y-3 overflow-y-auto py-4 text-xs">
          <div>
            <Label htmlFor="stock-sku-price" className="mb-1.5 block text-zinc-700">
              价格(¥)
            </Label>
            <Input
              id="stock-sku-price"
              className="h-auto w-full rounded-lg border-zinc-300 px-3 py-2 shadow-none focus-visible:ring-0"
              placeholder="如 329"
              value={patch.price}
              onChange={(e) => setPatch({ ...patch, price: e.target.value })}
            />
          </div>
          <div>
            <Label htmlFor="stock-sku-stock" className="mb-1.5 block text-zinc-700">
              库存
            </Label>
            <Input
              id="stock-sku-stock"
              className="h-auto w-full rounded-lg border-zinc-300 px-3 py-2 shadow-none focus-visible:ring-0"
              placeholder="如 50"
              value={patch.stock}
              onChange={(e) => setPatch({ ...patch, stock: e.target.value })}
            />
          </div>
        </div>
        <DialogFooter className="gap-2 pt-3 sm:gap-0 border-t border-zinc-100">
          <Button type="button" variant="outline" size="sm" onClick={onClose} className="text-xs cursor-pointer">
            取消
          </Button>
          <Button
            type="button"
            size="sm"
            disabled={!ready}
            onClick={() => void submit()}
            className="text-xs font-bold cursor-pointer"
          >
            保存
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
