import {
  DenseTable,
  DenseTableBody,
  DenseTableCell,
  DenseTableHead,
  DenseTableHeader,
  DenseTableRow,
} from '@/components/dense-table';
import { type Sku, type Spu, api } from '@/lib/api';
import { useCallback, useEffect, useState } from 'react';
import { Button, Input } from 'ui';

interface Props {
  spu: Spu;
  onMsg: (m: string) => void;
}

const EMPTY_NEW = { skuTitle: '', price: '', stock: '' };

/** SKU 明细子表(承接 SPU 行展开):自持明细数据与新增/改价/删除,
 *  挂载即拉取;删除受"已有成交不可删"服务端护栏。 */
export function SkuSubTable({ spu, onMsg }: Props) {
  const [skus, setSkus] = useState<Sku[]>([]);
  const [newSku, setNewSku] = useState(EMPTY_NEW);
  const [skuEdit, setSkuEdit] = useState<{ id: string; price: string; stock: string } | null>(null);

  const loadSkus = useCallback(async () => {
    setSkus((await api.products.listSkus(spu.id)).skus || []);
  }, [spu.id]);
  useEffect(() => {
    void loadSkus();
  }, [loadSkus]);

  async function createSku() {
    const b = await api.products.createSku(spu.id, newSku);
    onMsg(b.success ? `✓ SKU ${b.skuCode} 已新增` : `失败:${b.message}`);
    if (b.success) {
      setNewSku(EMPTY_NEW);
      void loadSkus();
    }
  }

  async function saveSku(skuId: string, patch: { price: string; stock: string }) {
    const b = await api.products.updateSku(skuId, { price: Number(patch.price), stock: Number(patch.stock) });
    onMsg(b.success ? '✓ SKU 已保存' : `失败:${b.message}`);
    setSkuEdit(null);
    void loadSkus();
  }

  async function deleteSku(skuId: string) {
    const b = await api.products.removeSku(skuId);
    onMsg(b.success ? '✓ 已删除' : `失败:${b.message}`);
    void loadSkus();
  }

  return (
    <div>
      <div className="text-[11px] font-semibold text-zinc-500 mb-2">SKU 明细 · {spu.spu_code}</div>
      {/* 嵌套在 SPU 展开行内:!overflow-visible 关闭包裹层滚动,密度沿用外层极紧凑风 */}
      <DenseTable className="!overflow-visible text-[12px]">
        <DenseTableHeader>
          <DenseTableRow className="hover:bg-transparent">
            <DenseTableHead className="py-1 pr-4 text-[12px] text-zinc-400">SKU 编码</DenseTableHead>
            <DenseTableHead className="py-1 pr-4 text-[12px] text-zinc-400">价格</DenseTableHead>
            <DenseTableHead className="py-1 pr-4 text-[12px] text-zinc-400">库存</DenseTableHead>
            <DenseTableHead className="py-1 text-[12px] text-zinc-400">操作</DenseTableHead>
          </DenseTableRow>
        </DenseTableHeader>
        <DenseTableBody>
          {skus.map((k) => (
            <DenseTableRow key={k.id} className="border-b-0">
              <DenseTableCell className="py-1 pr-4 pl-0 font-mono">{k.sku_code}</DenseTableCell>
              <DenseTableCell className="py-1 pr-4 pl-0">¥{k.price}</DenseTableCell>
              <DenseTableCell className="py-1 pr-4 pl-0">{k.stock}</DenseTableCell>
              <DenseTableCell className="py-1 pl-0">
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => setSkuEdit({ id: k.id, price: String(k.price), stock: String(k.stock) })}
                >
                  改价/库存
                </Button>
                <Button size="sm" variant="ghost" className="text-rose-600" onClick={() => void deleteSku(k.id)}>
                  删除
                </Button>
              </DenseTableCell>
            </DenseTableRow>
          ))}
        </DenseTableBody>
      </DenseTable>
      {skuEdit && (
        <div className="mt-2 flex items-center gap-2 text-xs">
          <span className="text-zinc-500">改价/库存:</span>
          <Input
            className="h-auto w-24 rounded border-zinc-300 px-2 py-1 text-xs shadow-none focus-visible:ring-0"
            placeholder="价格"
            value={skuEdit.price}
            onChange={(e) => setSkuEdit({ ...skuEdit, price: e.target.value })}
          />
          <Input
            className="h-auto w-20 rounded border-zinc-300 px-2 py-1 text-xs shadow-none focus-visible:ring-0"
            placeholder="库存"
            value={skuEdit.stock}
            onChange={(e) => setSkuEdit({ ...skuEdit, stock: e.target.value })}
          />
          <Button size="sm" onClick={() => skuEdit && void saveSku(skuEdit.id, skuEdit)}>
            保存
          </Button>
        </div>
      )}
      <div className="mt-2 flex items-center gap-2 text-xs">
        <Input
          className="h-auto w-32 rounded border-zinc-300 px-2 py-1 text-xs shadow-none focus-visible:ring-0"
          placeholder="新 SKU 标题"
          value={newSku.skuTitle}
          onChange={(e) => setNewSku({ ...newSku, skuTitle: e.target.value })}
        />
        <Input
          className="h-auto w-24 rounded border-zinc-300 px-2 py-1 text-xs shadow-none focus-visible:ring-0"
          placeholder="价格"
          value={newSku.price}
          onChange={(e) => setNewSku({ ...newSku, price: e.target.value })}
        />
        <Input
          className="h-auto w-20 rounded border-zinc-300 px-2 py-1 text-xs shadow-none focus-visible:ring-0"
          placeholder="库存"
          value={newSku.stock}
          onChange={(e) => setNewSku({ ...newSku, stock: e.target.value })}
        />
        <Button size="sm" variant="outline" disabled={!newSku.price} onClick={() => void createSku()}>
          新增 SKU
        </Button>
      </div>
    </div>
  );
}
