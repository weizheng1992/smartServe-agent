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

export function SpusTab() {
  const {
    activeTab,
    filteredSpus, setSpuCategoryFilter, setSpuSearchQuery, spuCategories, spuCategoryFilter, spuSearchQuery, spus,
  } = useWorkbench();
  if (activeTab !== 'spus') return null;
  return (
    <>
          <div className="space-y-4">
            {/* 筛选与搜索 */}
            <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-2xs flex flex-wrap items-center justify-between gap-3">
              <div className="flex items-center gap-2 flex-wrap">
                <div className="flex bg-slate-200/80 p-0.5 rounded-lg text-xs font-semibold">
                  <button
                    type="button"
                    onClick={() => setSpuCategoryFilter('ALL')}
                    className={`px-3 py-1 rounded-md transition cursor-pointer ${
                      spuCategoryFilter === 'ALL'
                        ? 'bg-white text-slate-900 shadow-xs font-bold'
                        : 'text-slate-600 hover:text-slate-900'
                    }`}
                  >
                    全部品类 ({spus.length})
                  </button>
                  {spuCategories.map((cat) => (
                    <button
                      key={cat}
                      type="button"
                      onClick={() => setSpuCategoryFilter(cat)}
                      className={`px-3 py-1 rounded-md transition cursor-pointer ${
                        spuCategoryFilter === cat
                          ? 'bg-white text-slate-900 shadow-xs font-bold'
                          : 'text-slate-600 hover:text-slate-900'
                      }`}
                    >
                      {cat} ({spus.filter((s) => s.category === cat).length})
                    </button>
                  ))}
                </div>
              </div>

              <div className="flex items-center gap-2">
                <Input
                  type="text"
                  placeholder="搜索 SPU 编码 / 名称 / 品牌..."
                  value={spuSearchQuery}
                  onChange={(e) => setSpuSearchQuery(e.target.value)}
                  className="text-xs h-8 w-64 bg-white"
                />
              </div>
            </div>

            {filteredSpus.length === 0 ? (
              <div className="bg-white p-12 rounded-xl border border-slate-200 text-center space-y-2">
                <div className="text-3xl">🏷️</div>
                <h4 className="text-sm font-bold text-slate-800">暂无匹配 SPU 商品</h4>
                <p className="text-xs text-slate-400">请尝试切换分类或调整搜索关键字。</p>
              </div>
            ) : (
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {filteredSpus.map((spu) => (
                  <div key={spu.id} className="bg-white rounded-xl border border-slate-200 p-5 shadow-2xs space-y-3">
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <span className="text-[10px] bg-slate-100 text-slate-600 px-2 py-0.5 rounded font-mono">
                          {spu.spu_code}
                        </span>
                        <h4 className="font-bold text-slate-900 text-sm mt-1">{spu.title}</h4>
                        <p className="text-xs text-slate-500 mt-0.5">{spu.subtitle}</p>
                      </div>
                      <Badge
                        variant="outline"
                        className="text-xs bg-emerald-100 text-emerald-800 border-emerald-200 font-semibold shrink-0"
                      >
                        {spu.category}
                      </Badge>
                    </div>

                    {/* 规格维度 */}
                    <div className="bg-slate-50 p-3 rounded-lg border border-slate-200 space-y-1">
                      <span className="text-[11px] font-bold text-slate-700 block">📐 规格维度矩阵 (Dimensions)</span>
                      <div className="flex flex-wrap gap-2 pt-1">
                        {spu.spec_dimensions?.map((dim) => (
                          <span
                            key={dim.name}
                            className="text-xs bg-white text-slate-700 px-2 py-1 rounded border border-slate-200"
                          >
                            <strong>{dim.name}:</strong> {dim.values.join(' / ')}
                          </span>
                        ))}
                      </div>
                    </div>

                    {/* 参数 Specs */}
                    <div className="text-xs space-y-1 border-t border-slate-100 pt-2">
                      <span className="font-semibold text-slate-700">🔬 材质与技术参数:</span>
                      <div className="grid grid-cols-2 gap-1 text-[11px] text-slate-600">
                        {Object.entries(spu.specs || {}).map(([k, v]) => (
                          <div key={k}>
                            <span className="text-slate-400">{k}:</span> {v}
                          </div>
                        ))}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
    </>
  );
}
