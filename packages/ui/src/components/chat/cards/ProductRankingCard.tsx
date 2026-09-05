'use client';

import type React from 'react';
import type { ProductRankingCardData } from 'types';
import { Badge } from '../../ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '../../ui/card';

export interface ProductRankingCardProps {
  data: ProductRankingCardData;
  onSelectProduct?: (productId: string) => void;
}

export const ProductRankingCard: React.FC<ProductRankingCardProps> = ({ data, onSelectProduct }) => {
  const { metricLabel, products, summary } = data;

  return (
    <Card className="bg-slate-900/90 border-slate-800 text-slate-100 shadow-xl overflow-hidden max-w-lg">
      <CardHeader className="bg-slate-850/70 p-3.5 border-b border-slate-800 flex flex-row items-center justify-between">
        <div className="flex items-center space-x-2">
          <span className="text-base">🏆</span>
          <CardTitle className="text-xs font-semibold uppercase tracking-wider text-indigo-300">
            商品销售排行榜 · {metricLabel}
          </CardTitle>
        </div>
        <Badge variant="outline" className="border-indigo-500/30 text-indigo-300 bg-indigo-950/20 text-[10px]">
          共 {products.length} 款商品
        </Badge>
      </CardHeader>

      <CardContent className="p-3 space-y-2 text-xs">
        {summary && <p className="text-[11px] text-slate-400 pb-1 border-b border-slate-800/60">{summary}</p>}

        <div className="divide-y divide-slate-800/50">
          {products.map((p) => {
            const isTop1 = p.rank === 1;
            const isTop2 = p.rank === 2;
            const isTop3 = p.rank === 3;

            return (
              // biome-ignore lint/a11y/useKeyWithClickEvents: 榜单行点击为快捷跳转增强,非唯一交互路径
              <div
                key={p.productId}
                className="py-2.5 first:pt-1 last:pb-0 flex items-center justify-between gap-3 hover:bg-slate-800/30 px-1 rounded-md transition-colors"
                onClick={() => onSelectProduct?.(p.productId)}
              >
                <div className="flex items-center space-x-2.5 min-w-0">
                  <span
                    className={`h-5 w-5 rounded-full flex items-center justify-center text-[10px] font-bold shrink-0 ${
                      isTop1
                        ? 'bg-amber-500/20 text-amber-400 border border-amber-500/40'
                        : isTop2
                          ? 'bg-slate-400/20 text-slate-300 border border-slate-400/40'
                          : isTop3
                            ? 'bg-amber-700/20 text-amber-600 border border-amber-700/40'
                            : 'bg-slate-800 text-slate-500'
                    }`}
                  >
                    {p.rank}
                  </span>
                  <div className="min-w-0">
                    <h4 className="font-medium text-slate-200 truncate text-xs">{p.name}</h4>
                    <div className="flex items-center gap-2 text-[10px] text-slate-400 mt-0.5">
                      <span>单价: ¥{p.price}</span>
                      <span>•</span>
                      <span>销量: {p.totalVolume} 件</span>
                      <span>•</span>
                      <span>毛利率: {p.marginRate}</span>
                    </div>
                  </div>
                </div>

                <div className="text-right shrink-0">
                  <div className="text-xs font-semibold text-emerald-400 font-mono">
                    {p.metricDisplay || `¥${p.totalGmv.toLocaleString()}`}
                  </div>
                  <div className="text-[10px] text-slate-400">毛利 ¥{p.grossProfit.toLocaleString()}</div>
                </div>
              </div>
            );
          })}
        </div>
      </CardContent>
    </Card>
  );
};
