// SKU 库存筛选纯逻辑(独立模块便于单测);低库存阈值与工作台 SkusTab 同口径(50)。
import type { SkuStockRow } from '@/lib/api';

export const LOW_STOCK_THRESHOLD = 50;
export type StockFilter = 'ALL' | 'low' | 'normal';

export function filterSkuStock(skus: SkuStockRow[], filter: StockFilter, query: string): SkuStockRow[] {
  return skus.filter((s) => {
    if (filter === 'low' && s.stock >= LOW_STOCK_THRESHOLD) return false;
    if (filter === 'normal' && s.stock < LOW_STOCK_THRESHOLD) return false;
    if (query.trim()) {
      const q = query.toLowerCase().trim();
      const hit = `${s.sku_code} ${s.sku_title || ''} ${s.spu_title}`.toLowerCase().includes(q);
      if (!hit) return false;
    }
    return true;
  });
}
