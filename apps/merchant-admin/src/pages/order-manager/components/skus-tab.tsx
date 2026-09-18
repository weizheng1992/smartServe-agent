import React from "react";
import {
  ApprovalContextDrawer,
  ApprovalRiskBadge,
  Badge,
  Button,
  CheckCircle2,
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Input,
  RichCardRenderer,
  ShieldAlert,
  Textarea,
} from "ui";
import { useWorkbench } from "../workbench";

export function SkusTab() {
  const {
    activeTab,
    filteredSkus, lowStockCount, setSkuSearchQuery, setSkuStockFilter, skuSearchQuery, skuStockFilter, skus,
  } = useWorkbench();
  if (activeTab !== 'skus') return null;
  return (
    <>
          <div className="bg-white rounded-xl border border-slate-200 shadow-2xs overflow-hidden space-y-0">
            {/* 筛选与搜索 */}
            <div className="p-4 border-b border-slate-100 bg-slate-50/70 flex flex-wrap items-center justify-between gap-3">
              <div className="flex items-center gap-2 flex-wrap">
                <div className="flex bg-slate-200/80 p-0.5 rounded-lg text-xs font-semibold">
                  <button
                    type="button"
                    onClick={() => setSkuStockFilter('ALL')}
                    className={`px-3 py-1 rounded-md transition cursor-pointer ${
                      skuStockFilter === 'ALL'
                        ? 'bg-white text-slate-900 shadow-xs font-bold'
                        : 'text-slate-600 hover:text-slate-900'
                    }`}
                  >
                    全部 SKU ({skus.length})
                  </button>
                  <button
                    type="button"
                    onClick={() => setSkuStockFilter('low')}
                    className={`px-3 py-1 rounded-md transition cursor-pointer flex items-center gap-1.5 ${
                      skuStockFilter === 'low'
                        ? 'bg-white text-rose-700 shadow-xs font-bold'
                        : 'text-slate-600 hover:text-slate-900'
                    }`}
                  >
                    <span>⚠️ 低库存预警 (&lt;50)</span>
                    <span className="bg-rose-100 text-rose-700 text-[10px] px-1.5 py-0.2 rounded-full font-bold">
                      {lowStockCount}
                    </span>
                  </button>
                  <button
                    type="button"
                    onClick={() => setSkuStockFilter('normal')}
                    className={`px-3 py-1 rounded-md transition cursor-pointer ${
                      skuStockFilter === 'normal'
                        ? 'bg-white text-slate-900 shadow-xs font-bold'
                        : 'text-slate-600 hover:text-slate-900'
                    }`}
                  >
                    充足库存 (≥50)
                  </button>
                </div>
              </div>

              <div className="flex items-center gap-2">
                <Input
                  type="text"
                  placeholder="搜索 SKU 编码 / 规格 / SPU 标题..."
                  value={skuSearchQuery}
                  onChange={(e) => setSkuSearchQuery(e.target.value)}
                  className="text-xs h-8 w-64 bg-white"
                />
              </div>
            </div>

            {filteredSkus.length === 0 ? (
              <div className="p-12 text-center space-y-2">
                <div className="text-3xl">📦</div>
                <h4 className="text-sm font-bold text-slate-800">暂无匹配的 SKU 记录</h4>
                <p className="text-xs text-slate-400">请调整搜索关键词或库存状态过滤条件。</p>
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs">
                  <thead className="bg-slate-50 border-b border-slate-200 text-slate-500 uppercase font-semibold">
                    <tr>
                      <th className="p-3.5">SKU 编码</th>
                      <th className="p-3.5">SKU 规格名称</th>
                      <th className="p-3.5">所属 SPU</th>
                      <th className="p-3.5">规格属性快照</th>
                      <th className="p-3.5">独立售价</th>
                      <th className="p-3.5">当前可用库存</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100 text-slate-700">
                    {filteredSkus.map((item) => (
                      <tr key={item.sku_code} className="hover:bg-slate-50/80 transition">
                        <td className="p-3.5 font-mono text-slate-600 font-semibold">{item.sku_code}</td>
                        <td className="p-3.5 font-bold text-slate-900">{item.sku_title}</td>
                        <td className="p-3.5 text-slate-500">{item.spu_title}</td>
                        <td className="p-3.5">
                          <div className="flex flex-wrap gap-1">
                            {Object.entries(item.spec_attributes || {}).map(([k, v]) => (
                              <span
                                key={k}
                                className="text-[10px] bg-slate-100 text-slate-700 px-1.5 py-0.5 rounded border border-slate-200"
                              >
                                {k}: {v}
                              </span>
                            ))}
                          </div>
                        </td>
                        <td className="p-3.5 font-extrabold text-emerald-600">¥{Number(item.price).toFixed(2)}</td>
                        <td className="p-3.5">
                          <span
                            className={`font-semibold px-2 py-0.5 rounded text-xs ${
                              item.stock < 50
                                ? 'bg-rose-100 text-rose-700 font-bold border border-rose-200'
                                : 'text-slate-800'
                            }`}
                          >
                            {item.stock} 件
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
    </>
  );
}
