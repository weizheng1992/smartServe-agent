import { type Sku, type Spu, api } from '@/lib/api';
import { useCallback, useEffect, useState } from 'react';
import { Button } from 'ui';

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
      <table className="w-full text-[12px]">
        <thead>
          <tr className="text-left text-zinc-400">
            <th className="py-1 pr-4 font-medium">SKU 编码</th>
            <th className="py-1 pr-4 font-medium">价格</th>
            <th className="py-1 pr-4 font-medium">库存</th>
            <th className="py-1 font-medium">操作</th>
          </tr>
        </thead>
        <tbody>
          {skus.map((k) => (
            <tr key={k.id}>
              <td className="py-1 pr-4 font-mono">{k.sku_code}</td>
              <td className="py-1 pr-4">¥{k.price}</td>
              <td className="py-1 pr-4">{k.stock}</td>
              <td className="py-1">
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
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {skuEdit && (
        <div className="mt-2 flex items-center gap-2 text-xs">
          <span className="text-zinc-500">改价/库存:</span>
          <input
            className="w-24 rounded border border-zinc-300 px-2 py-1"
            placeholder="价格"
            value={skuEdit.price}
            onChange={(e) => setSkuEdit({ ...skuEdit, price: e.target.value })}
          />
          <input
            className="w-20 rounded border border-zinc-300 px-2 py-1"
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
        <input
          className="w-32 rounded border border-zinc-300 px-2 py-1"
          placeholder="新 SKU 标题"
          value={newSku.skuTitle}
          onChange={(e) => setNewSku({ ...newSku, skuTitle: e.target.value })}
        />
        <input
          className="w-24 rounded border border-zinc-300 px-2 py-1"
          placeholder="价格"
          value={newSku.price}
          onChange={(e) => setNewSku({ ...newSku, price: e.target.value })}
        />
        <input
          className="w-20 rounded border border-zinc-300 px-2 py-1"
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
