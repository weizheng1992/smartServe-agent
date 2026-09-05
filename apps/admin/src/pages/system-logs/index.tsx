import React, { useCallback } from 'react';
import { DataTable, FilterBar } from '../../components/crud';
import { useAdminCrud } from '../../hooks/useAdminCrud';
import { systemLogsApi } from '../../lib/api';
import { LogDetailDrawer } from './components/LogDetailDrawer';
import type { SystemLogRecord } from './types';

export * from './types';

export function SystemLogsPage() {
  const fetchLogsList = useCallback(async ({ tenantId, status }: { tenantId: string; status?: string }) => {
    try {
      const res = await systemLogsApi.list({
        tenantId: tenantId === 'all' ? undefined : tenantId,
        level: status || undefined,
        limit: 50,
      });
      if (res.success && Array.isArray(res.data)) {
        return res.data;
      }
    } catch (err) {
      console.warn('Failed to fetch remote system logs:', err);
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
    isDrawerOpen,
    selectedItem,
    openDrawer,
    closeDrawer,
  } = useAdminCrud<SystemLogRecord>({
    fetchList: fetchLogsList,
    tenantKey: 'businessId' as keyof SystemLogRecord,
    filterFn: (item, query, logType, tenantId) => {
      if (tenantId !== 'all' && item.businessId !== tenantId) return false;
      if (logType && item.logType !== logType) return false;
      if (query.trim()) {
        const q = query.toLowerCase();
        return (
          item.id.toLowerCase().includes(q) ||
          item.traceId.toLowerCase().includes(q) ||
          item.model.toLowerCase().includes(q)
        );
      }
      return true;
    },
  });

  const columns = [
    {
      key: 'id',
      header: '日志 ID / Trace ID',
      render: (row: SystemLogRecord) => (
        <div>
          <div className="font-semibold text-slate-900 font-mono text-xs">{row.id}</div>
          <div className="text-xs text-slate-400 font-mono">Trace: {row.traceId}</div>
        </div>
      ),
    },
    {
      key: 'businessId',
      header: '商户租户',
      render: (row: SystemLogRecord) => (
        <span
          className={`inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium ${
            row.businessId === 'nike'
              ? 'bg-rose-50 text-rose-700'
              : row.businessId === 'adidas'
                ? 'bg-blue-50 text-blue-700'
                : 'bg-amber-50 text-amber-700'
          }`}
        >
          {row.businessId.toUpperCase()}
        </span>
      ),
    },
    {
      key: 'logType',
      header: '日志类型 / 模型',
      render: (row: SystemLogRecord) => (
        <div>
          <span className="text-xs font-semibold text-slate-800 bg-slate-100 px-2 py-0.5 rounded mr-1.5">
            {row.logType}
          </span>
          <span className="text-xs font-mono text-slate-500">{row.model}</span>
        </div>
      ),
    },
    {
      key: 'totalTokens',
      header: 'Tokens (Prompt + Compl)',
      render: (row: SystemLogRecord) => (
        <div>
          <span className="text-xs font-mono font-semibold text-slate-800">{row.totalTokens}</span>
          <span className="text-[10px] text-slate-400 font-mono ml-1">
            ({row.promptTokens}+{row.completionTokens})
          </span>
        </div>
      ),
    },
    {
      key: 'latencyMs',
      header: '耗时 Latency',
      render: (row: SystemLogRecord) => (
        <span className={`text-xs font-mono font-bold ${row.latencyMs > 1000 ? 'text-amber-600' : 'text-emerald-600'}`}>
          {row.latencyMs}ms
        </span>
      ),
    },
    {
      key: 'timestamp',
      header: '时间',
      render: (row: SystemLogRecord) => <span className="text-xs text-slate-400 font-mono">{row.timestamp}</span>,
    },
  ];

  return (
    <div className="space-y-4">
      <FilterBar
        searchQuery={searchQuery}
        onSearchChange={setSearchQuery}
        searchPlaceholder="搜索日志ID、TraceID、模型..."
        statusFilter={statusFilter}
        onStatusChange={setStatusFilter}
        statusOptions={[
          { label: 'LLM 调用日志', value: 'llm_call' },
          { label: '意图分类日志', value: 'intent_triage' },
          { label: '会话遥测汇总', value: 'session_metric' },
          { label: '工具执行日志', value: 'tool_execution' },
          { label: '系统异常告警', value: 'system_error' },
        ]}
        showTenantFilter={true}
        onReset={handleResetFilters}
      />

      <DataTable<SystemLogRecord>
        columns={columns}
        data={paginatedData}
        emptyText="未检索到符合条件的系统日志"
        onRowClick={openDrawer}
        pagination={{
          currentPage,
          pageSize,
          total,
          onPageChange: setCurrentPage,
        }}
      />

      <LogDetailDrawer isOpen={isDrawerOpen} onClose={closeDrawer} log={selectedItem} />
    </div>
  );
}
export default SystemLogsPage;
