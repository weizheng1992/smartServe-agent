import React from "react";
import { DataTable, FilterBar } from "../../components/crud";
import { useAdminCrud } from "../../hooks/useAdminCrud";
import { EvalMetricsSummary } from "./components/EvalMetricsSummary";
import { Badge, Progress } from "ui";
import type { EvalRunRecord } from "./types";

export * from "./types";

const INITIAL_EVALS: EvalRunRecord[] = [
  {
    id: "eval_run_20260223_v3",
    runName: "Engine v2.4 对话策略金标回归评测",
    datasetName: "ecommerce_golden_dialogue_v2",
    sampleCount: 150,
    toolAccuracy: 0.98,
    ragFaithfulness: 0.95,
    hitlTriggerRate: 0.12,
    status: "completed",
    createdAt: "2026-02-23 14:00:00",
  },
  {
    id: "eval_run_20260222_v2",
    runName: "Prompt 深度思考链消融实验 (ReAct vs Graph)",
    datasetName: "refund_edge_cases_100",
    sampleCount: 100,
    toolAccuracy: 0.92,
    ragFaithfulness: 0.89,
    hitlTriggerRate: 0.25,
    status: "completed",
    createdAt: "2026-02-22 18:30:00",
  },
  {
    id: "eval_run_20260221_v1",
    runName: "多语言与多商户意图分发鲁棒性测试",
    datasetName: "multilingual_intent_test_50",
    sampleCount: 50,
    toolAccuracy: 0.96,
    ragFaithfulness: 0.94,
    hitlTriggerRate: 0.08,
    status: "completed",
    createdAt: "2026-02-21 10:15:00",
  },
];

export function EvalsPage() {
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
    initialData: INITIAL_EVALS,
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
      key: "runName",
      header: "评测批次 / 数据集",
      render: (row: EvalRunRecord) => (
        <div>
          <div className="font-semibold text-slate-900 text-xs">
            {row.runName}
          </div>
          <div className="text-xs text-slate-400 font-mono mt-0.5">
            Dataset: {row.datasetName} ({row.sampleCount} 样本)
          </div>
        </div>
      ),
    },
    {
      key: "toolAccuracy",
      header: "工具调用准确率 (Tool Accuracy)",
      render: (row: EvalRunRecord) => (
        <div className="flex items-center gap-2">
          <Progress value={row.toolAccuracy * 100} className="w-16 h-2" />
          <span className="text-xs font-bold font-mono text-slate-800">
            {(row.toolAccuracy * 100).toFixed(1)}%
          </span>
        </div>
      ),
    },
    {
      key: "ragFaithfulness",
      header: "RAG 事实忠实度 (Faithfulness)",
      render: (row: EvalRunRecord) => (
        <div className="flex items-center gap-2">
          <Progress value={row.ragFaithfulness * 100} className="w-16 h-2" />
          <span className="text-xs font-bold font-mono text-slate-800">
            {(row.ragFaithfulness * 100).toFixed(1)}%
          </span>
        </div>
      ),
    },
    {
      key: "hitlTriggerRate",
      header: "HITL 风控触发率",
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
      key: "status",
      header: "状态",
      render: (_row: EvalRunRecord) => (
        <Badge
          variant="outline"
          className="bg-emerald-50 text-emerald-700 border-emerald-200"
        >
          已完成
        </Badge>
      ),
    },
    {
      key: "createdAt",
      header: "执行时间",
      render: (row: EvalRunRecord) => (
        <span className="text-xs text-slate-400 font-mono">
          {row.createdAt}
        </span>
      ),
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
