import React, { useCallback } from 'react';
import { Badge, Progress } from 'ui';
import { DataTable, FilterBar } from '../../components/crud';
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
          emptyText="暂无评测运行记录"
          pagination={{
            currentPage,
            pageSize,
            total,
            onPageChange: setCurrentPage,
          }}
        />
      </div>
    </div>
  );
}
export default EvalsPage;
