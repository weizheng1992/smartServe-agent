import React from "react";

export interface RagPlaygroundProps {
  selectedTenantId: string;
  query: string;
  onQueryChange: (val: string) => void;
  onSearch: () => void;
  isSearching: boolean;
  results: Array<{ id: string; title: string; score: number; content: string }>;
}

export function RagPlayground({
  selectedTenantId,
  query,
  onQueryChange,
  onSearch,
  isSearching,
  results,
}: RagPlaygroundProps) {
  return (
    <div className="bg-white border border-slate-200 rounded-xl p-4 shadow-xs">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <div className="w-2 h-2 rounded-full bg-indigo-600" />
          <h3 className="text-xs font-semibold text-slate-900 uppercase tracking-wider">
            RAG 向量检索在线演练台 (Playground)
          </h3>
        </div>
        <span className="text-[11px] text-slate-400">
          隔离租户:{" "}
          <strong className="text-slate-700 font-mono">
            {selectedTenantId}
          </strong>
        </span>
      </div>

      <div className="flex items-center gap-2">
        <input
          type="text"
          value={query}
          onChange={(e) => onQueryChange(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && onSearch()}
          placeholder="输入自然语言测试 Query，如：退货需要满足什么条件？ZoomX 跑鞋特点？"
          className="flex-1 px-3 py-1.5 text-xs bg-slate-50 border border-slate-200 rounded-lg focus:outline-hidden focus:bg-white focus:border-indigo-500 transition-colors"
        />
        <button
          type="button"
          disabled={isSearching || !query.trim()}
          onClick={onSearch}
          className="px-4 py-1.5 text-xs font-medium bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg transition-colors shadow-xs flex items-center gap-1.5 cursor-pointer disabled:opacity-50"
        >
          {isSearching ? "检索中..." : "发起检索测试"}
        </button>
      </div>

      {results.length > 0 && (
        <div className="mt-3.5 space-y-2 pt-3 border-t border-slate-100">
          <div className="text-[11px] font-semibold text-slate-500">
            召回 Top-{results.length} 相关切片:
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-2.5">
            {results.map((hit) => (
              <div
                key={hit.id}
                className="p-3 bg-slate-50/80 border border-slate-200 rounded-lg text-xs space-y-1.5"
              >
                <div className="flex items-center justify-between">
                  <span className="font-semibold text-slate-800">
                    {hit.title}
                  </span>
                  <span className="px-1.5 py-0.5 rounded font-mono text-[10px] font-bold bg-emerald-100 text-emerald-800">
                    Score: {(hit.score * 100).toFixed(1)}%
                  </span>
                </div>
                <p className="text-slate-600 text-[11px] leading-relaxed line-clamp-3">
                  {hit.content}
                </p>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
