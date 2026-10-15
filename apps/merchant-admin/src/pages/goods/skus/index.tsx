import { type SkuStockRow, api } from '@/lib/api';
import { useListPage } from '@/lib/use-list-page';
import { SkuStockTable } from './components/sku-stock-table';

// SKU 库存(独立库存视角页):跨 SPU 的 SKU 总表,低库存筛选 + 行内改价/改库存。
// 与「商品列表」分工:结构性增删(新 SKU/删除)在商品列表的展开子表,这里只管库存。
export default function SkusPage() {
  const {
    rows: skus,
    msg,
    setMsg,
    reload,
  } = useListPage<SkuStockRow>(async () => (await api.products.listAllSkus()).skus || []);

  return (
    <div className="mx-auto max-w-5xl space-y-4">
      <SkuStockTable skus={skus} onMsg={setMsg} onChanged={() => void reload()} />
      {msg && <div className="text-[11px] text-zinc-400">{msg}</div>}
    </div>
  );
}
