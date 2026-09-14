import React, { useCallback, useState } from 'react';
import { Badge, Progress } from 'ui';
import { DataTable, DetailDrawer, FilterBar } from '../../components/crud';
import { useAdminCrud } from '../../hooks/useAdminCrud';
import { evalsApi } from '../../lib/api';
import { EvalMetricsSummary } from './components/EvalMetricsSummary';
import type { EvalRunRecord } from './types';

export * from './types';

export function EvalsPage() {
  const fetchEvalsList = useCallback(async () => {
    try {
      const res = await evalsApi.getResults();
      if (res.success && Array.isArray(res.data)) {
        return res.data;
      }
    } catch (err) {
      console.warn('Failed to fetch remote evals:', err);
    }
    return [];
  }, []);

  const {
    paginatedData,
    total,
    currentPage,
    setCurrentPage,
    pageSize,
    searchQuery,
    setSearchQuery,
    statusFilter,
    setStatusFilter,
    handleResetFilters,
  } = useAdminCrud<EvalRunRecord>({
    fetchList: fetchEvalsList,
    filterFn: (item, query, status) => {
      if (status && item.status !== status) return false;
      if (query.trim()) {
        const q = query.toLowerCase();
        return (
          item.runName.toLowerCase().includes(q) ||
          item.datasetName.toLowerCase().includes(q) ||
          item.id.toLowerCase().includes(q)
        );
      }
      return true;
    },
  });

  // 样本下钻(admin-readiness 10):行点击 → 抽屉列出该批次逐用例结果
  const [casesOpen, setCasesOpen] = useState(false);
  const [casesRun, setCasesRun] = useState<EvalRunRecord | null>(null);
  const [cases, setCases] = useState<
    Array<{ caseName: string; passed: boolean | null; score: number; latencyMs?: number; error?: string }>
  >([]);
  const [isLoadingCases, setIsLoadingCases] = useState(false);

  const openCases = useCallback(async (row: EvalRunRecord) => {
    setCasesRun(row);
    setCasesOpen(true);
    setIsLoadingCases(true);
    setCases([]);
    try {
      const json = await evalsApi.getResultCases(row.id);
      if (json.success && Array.isArray(json.data)) setCases(json.data);
    } catch (err) {
      console.warn('Failed to fetch eval cases:', err);
    } finally {
      setIsLoadingCases(false);
    }
  }, []);

  const columns = [
    {
      key: 'runName',
      header: '评测批次 / 数据集',
      render: (row: EvalRunRecord) => (
        <div>
          <div className="font-semibold text-slate-900 text-xs">{row.runName}</div>
          <div className="text-xs text-slate-400 font-mono mt-0.5">
            Dataset: {row.datasetName} ({row.sampleCount} 样本)
          </div>
        </div>
      ),
    },
    {
      key: 'toolAccuracy',
      header: '工具调用准确率 (Tool Accuracy)',
      render: (row: EvalRunRecord) => (
        <div className="flex items-center gap-2">
          <Progress value={row.toolAccuracy * 100} className="w-16 h-2" />
          <span className="text-xs font-bold font-mono text-slate-800">{(row.toolAccuracy * 100).toFixed(1)}%</span>
        </div>
      ),
    },
    {
      key: 'ragFaithfulness',
      header: 'RAG 事实忠实度 (Faithfulness)',
      render: (row: EvalRunRecord) => (
        <div className="flex items-center gap-2">
          <Progress value={row.ragFaithfulness * 100} className="w-16 h-2" />
          <span className="text-xs font-bold font-mono text-slate-800">{(row.ragFaithfulness * 100).toFixed(1)}%</span>
        </div>
      ),
    },
    {
      key: 'hitlTriggerRate',
      header: 'HITL 风控触发率',
      render: (row: EvalRunRecord) => (
        <Badge
          variant="outline"
          className="text-xs font-mono font-semibold text-amber-700 bg-amber-50 border-amber-200"
        >
          {(row.hitlTriggerRate * 100).toFixed(1)}%
        </Badge>
      ),
    },
    {
      key: 'status',
      header: '状态',
      render: (_row: EvalRunRecord) => (
        <Badge variant="outline" className="bg-emerald-50 text-emerald-700 border-emerald-200">
          已完成
        </Badge>
      ),
    },
    {
      key: 'createdAt',
      header: '执行时间',
      render: (row: EvalRunRecord) => <span className="text-xs text-slate-400 font-mono">{row.createdAt}</span>,
    },
  ];

  return (
    <div className="space-y-6">
      <EvalMetricsSummary />

      <div className="space-y-4">
        <FilterBar
          searchQuery={searchQuery}
          onSearchChange={setSearchQuery}
          searchPlaceholder="搜索评测批次名、数据集名称..."
          statusFilter={statusFilter}
          onStatusChange={setStatusFilter}
          onReset={handleResetFilters}
        />

        <DataTable<EvalRunRecord>
          columns={columns}
          data={paginatedData}
          onRowClick={openCases}
          emptyText="暂无评测运行记录"
          pagination={{
            currentPage,
            pageSize,
            total,
            onPageChange: setCurrentPage,
          }}
        />
      </div>

      <DetailDrawer
        isOpen={casesOpen}
        onClose={() => setCasesOpen(false)}
        width="sm:max-w-2xl"
        title={`评测样本下钻: ${casesRun?.runName ?? ''}`}
        subtitle={`Dataset: ${casesRun?.datasetName} · ${cases?.length ?? 0} 条样本(逐用例真算,失败样例附错误)`}
      >
        {isLoadingCases ? (
          <div className="text-center py-10 text-xs text-slate-400">正在加载样本数据...</div>
        ) : cases.length === 0 ? (
          <div className="text-center py-10 text-xs text-slate-400">该批次无逐用例样本数据(诚实空,不伪造)</div>
        ) : (
          <div className="space-y-2">
            {cases.map((c) => (
              <div
                key={c.caseName}
                className={`p-3 rounded-xl border text-xs space-y-1 ${
                  c.passed === false ? 'bg-rose-50 border-rose-200' : 'bg-slate-50 border-slate-200'
                }`}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="font-semibold text-slate-800">{c.caseName}</span>
                  <span
                    className={`px-2 py-0.5 rounded-full font-medium ${
                      c.passed === false ? 'bg-rose-100 text-rose-700' : 'bg-emerald-100 text-emerald-700'
                    }`}
                  >
                    {c.passed === false ? '失败' : '通过'}
                  </span>
                </div>
                <div className="text-slate-500 font-mono text-[11px]">
                  score {(c.score * 100).toFixed(1)}%{c.latencyMs ? ` · ${Math.round(c.latencyMs)}ms` : ''}
                </div>
                {c.error && <div className="text-rose-600 text-[11px] whitespace-pre-wrap">{c.error}</div>}
              </div>
            ))}
          </div>
        )}
      </DetailDrawer>
    </div>
  );
}
export default EvalsPage;
