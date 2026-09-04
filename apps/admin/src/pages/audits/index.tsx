import React, { useCallback, useState } from 'react';
import { DataTable, FilterBar } from '../../components/crud';
import { useAdminCrud } from '../../hooks/useAdminCrud';
import { approvalsApi } from '../../lib/api';
import { AuditDetailDrawer } from './components/AuditDetailDrawer';
import type { AuditRecord } from './types';

export * from './types';

export function AuditsPage() {
  const fetchApprovals = useCallback(async ({ tenantId, status }: { tenantId: string; status?: string }) => {
    const res = await approvalsApi.list({
      tenantId,
      status: status || undefined,
    });

    if (res.success && Array.isArray(res.approvals)) {
      const records: AuditRecord[] = res.approvals.map((item: any) => ({
        id: item.id || item.approvalId,
        threadId: item.threadId,
        businessId: item.businessId || tenantId || 'ecommerce',
        actionType: item.toolName || item.actionType || 'executeAction',
        actionPayload:
          typeof item.actionPayload === 'object' && item.actionPayload !== null
            ? item.actionPayload
            : typeof item.toolInput === 'object' && item.toolInput !== null
              ? item.toolInput
              : { raw: item.toolInput || item.actionPayload },
        status: item.status || 'waiting',
        reviewerId: item.operatorId || item.reviewerId,
        rejectionReason: item.rejectionReason,
        createdAt: item.createdAt
          ? new Date(item.createdAt).toLocaleString('zh-CN')
          : new Date().toLocaleString('zh-CN'),
        resolvedAt: item.resolvedAt ? new Date(item.resolvedAt).toLocaleString('zh-CN') : undefined,
      }));
      return { data: records, total: records.length };
    }

    return { data: [], total: 0 };
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
    refetch,
    updateItem,
  } = useAdminCrud<AuditRecord>({
    fetchList: fetchApprovals,
    tenantKey: 'businessId' as keyof AuditRecord,
    filterFn: (item, query, status, tenantId): boolean => {
      if (tenantId !== 'all' && item.businessId !== tenantId) return false;
      if (status && item.status !== status) return false;
      if (query.trim()) {
        const q = query.toLowerCase();
        return Boolean(
          item.id.toLowerCase().includes(q) ||
            item.threadId.toLowerCase().includes(q) ||
            item.actionType.toLowerCase().includes(q) ||
            (item.reviewerId && item.reviewerId.toLowerCase().includes(q)),
        );
      }
      return true;
    },
  });

  const [isActing, setIsActing] = useState(false);

  // 平台介入人工决议 (对接真实 approvalsApi.resolve)
  const handleResolveAction = async (action: 'approved' | 'rejected') => {
    if (!selectedItem) return;
    setIsActing(true);
    try {
      const apiAction = action === 'approved' ? 'approve' : 'reject';
      await approvalsApi.resolve({
        approvalId: selectedItem.id,
        threadId: selectedItem.threadId,
        action: apiAction,
        rejectionReason: action === 'rejected' ? '平台管理员依据风控策略驳回' : undefined,
        tenantId: selectedItem.businessId,
      });

      await updateItem('id', {
        ...selectedItem,
        status: action,
        reviewerId: 'platform_admin_override',
        resolvedAt: new Date().toISOString().replace('T', ' ').slice(0, 19),
        rejectionReason: action === 'rejected' ? '平台管理员依据风控策略驳回' : undefined,
      });
      await refetch();
      closeDrawer();
    } catch (err) {
      console.error('Failed to resolve approval:', err);
    } finally {
      setIsActing(false);
    }
  };

  const columns = [
    {
      key: 'id',
      header: '审批工单 ID / 会话',
      render: (row: AuditRecord) => (
        <div>
          <div className="font-semibold text-slate-900 font-mono text-xs">{row.id}</div>
          <div className="text-xs text-slate-400 font-mono">Thread: {row.threadId}</div>
        </div>
      ),
    },
    {
      key: 'businessId',
      header: '商户租户',
      render: (row: AuditRecord) => (
        <span
          className={`inline-flex items-center px-2 py-0.5 rounded text-[11px] font-medium ${
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
      key: 'actionType',
      header: '触发动作 / 详情',
      render: (row: AuditRecord) => (
        <div>
          <span className="text-xs font-semibold text-slate-800 bg-slate-100 px-2 py-0.5 rounded mr-1.5">
            {row.actionType}
          </span>
          <span className="text-xs text-slate-500 truncate inline-block max-w-[200px] align-bottom">
            {JSON.stringify(row.actionPayload)}
          </span>
        </div>
      ),
    },
    {
      key: 'status',
      header: '审批状态',
      render: (row: AuditRecord) => {
        const map = {
          waiting: {
            label: '待审批 (Waiting)',
            cls: 'bg-amber-50 text-amber-700 border-amber-200',
          },
          approved: {
            label: '已通过 (Approved)',
            cls: 'bg-emerald-50 text-emerald-700 border-emerald-200',
          },
          rejected: {
            label: '已驳回 (Rejected)',
            cls: 'bg-rose-50 text-rose-700 border-rose-200',
          },
          timed_out: {
            label: '已超时 (Timed Out)',
            cls: 'bg-slate-100 text-slate-500 border-slate-200',
          },
        };
        const st = map[row.status] || map.waiting;
        return (
          <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium border ${st.cls}`}>
            {st.label}
          </span>
        );
      },
    },
    {
      key: 'reviewerId',
      header: '审批人 / 驳回理由',
      render: (row: AuditRecord) => (
        <div>
          <div className="text-xs text-slate-700 font-medium">{row.reviewerId || '-'}</div>
          {row.rejectionReason && (
            <div className="text-[11px] text-rose-500 truncate max-w-xs mt-0.5">{row.rejectionReason}</div>
          )}
        </div>
      ),
    },
    {
      key: 'createdAt',
      header: '提交时间',
      render: (row: AuditRecord) => <span className="text-xs text-slate-400 font-mono">{row.createdAt}</span>,
    },
  ];

  return (
    <div className="space-y-4">
      <FilterBar
        searchQuery={searchQuery}
        onSearchChange={setSearchQuery}
        searchPlaceholder="搜索工单ID、会话ID、操作类型、审批人..."
        statusFilter={statusFilter}
        onStatusChange={setStatusFilter}
        statusOptions={[
          { label: '待审批 (Waiting)', value: 'waiting' },
          { label: '已通过 (Approved)', value: 'approved' },
          { label: '已驳回 (Rejected)', value: 'rejected' },
          { label: '已超时 (Timed Out)', value: 'timed_out' },
        ]}
        showTenantFilter={true}
        onReset={handleResetFilters}
      />

      <DataTable<AuditRecord>
        columns={columns}
        data={paginatedData}
        emptyText="未检索到符合条件的风控审批记录"
        onRowClick={openDrawer}
        pagination={{
          currentPage,
          pageSize,
          total,
          onPageChange: setCurrentPage,
        }}
      />

      <AuditDetailDrawer
        isOpen={isDrawerOpen}
        onClose={closeDrawer}
        audit={selectedItem}
        onResolveAction={handleResolveAction}
        isActing={isActing}
      />
    </div>
  );
}
export default AuditsPage;
