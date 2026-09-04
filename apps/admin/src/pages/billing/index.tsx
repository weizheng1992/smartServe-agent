import React, { useCallback, useState } from 'react';
import { DataTable, FilterBar } from '../../components/crud';
import { useAdminCrud } from '../../hooks/useAdminCrud';
import { billingApi } from '../../lib/api';
import { BillingStatsSummary } from './components/BillingStatsSummary';
import { QuotaFormModal } from './components/QuotaFormModal';
import type { TenantBillingRecord } from './types';

export * from './types';

export function BillingPage() {
  const fetchBillingList = useCallback(async () => {
    try {
      const res = await billingApi.listTenantUsages();
      if (res.success && Array.isArray(res.data)) {
        return res.data;
      }
    } catch (err) {
      console.warn('Failed to fetch remote billing usages:', err);
    }
    return [];
  }, []);

  const updateQuotaApi = useCallback(async (item: TenantBillingRecord) => {
    await billingApi.updateQuota(item.businessId, item.monthlyLimitTokens);
    return item;
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
    isEditOpen,
    setIsEditOpen,
    selectedItem,
    openEdit,
    updateItem,
  } = useAdminCrud<TenantBillingRecord>({
    fetchList: fetchBillingList,
    updateApi: updateQuotaApi,
    tenantKey: 'businessId' as keyof TenantBillingRecord,
    filterFn: (item, query, status, tenantId) => {
      if (tenantId !== 'all' && item.businessId !== tenantId) return false;
      if (status && item.billingStatus !== status) return false;
      if (query.trim()) {
        const q = query.toLowerCase();
        return item.businessId.toLowerCase().includes(q) || item.tenantName.toLowerCase().includes(q);
      }
      return true;
    },
  });

  const [formData, setFormData] = useState<Partial<TenantBillingRecord>>({});

  const handleOpenEditQuota = (item: TenantBillingRecord) => {
    setFormData({ ...item });
    openEdit(item);
  };

  const handleSaveQuota = (e: React.FormEvent) => {
    e.preventDefault();
    if (selectedItem && formData.businessId) {
      updateItem('businessId', {
        ...selectedItem,
        monthlyLimitTokens: Number(formData.monthlyLimitTokens) || 5000000,
      });
    }
  };

  const columns = [
    {
      key: 'tenantName',
      header: '商户租户 / ID',
      render: (row: TenantBillingRecord) => (
        <div>
          <div className="font-semibold text-slate-900 text-xs">{row.tenantName}</div>
          <div className="text-xs text-slate-400 font-mono">ID: {row.businessId}</div>
        </div>
      ),
    },
    {
      key: 'totalTokens',
      header: '本月 Token 消耗 / 水位',
      render: (row: TenantBillingRecord) => {
        const usagePct = (row.totalTokens / row.monthlyLimitTokens) * 100;
        return (
          <div>
            <div className="flex items-center gap-2">
              <span className="text-xs font-semibold text-slate-800">{row.totalTokens.toLocaleString()}</span>
              <span className="text-[11px] text-slate-400">/ {(row.monthlyLimitTokens / 1000000).toFixed(1)}M</span>
            </div>
            <div className="w-32 bg-slate-100 rounded-full h-1.5 mt-1 overflow-hidden">
              <div
                className={`h-full rounded-full ${usagePct > 80 ? 'bg-rose-500' : 'bg-emerald-500'}`}
                style={{ width: `${Math.min(usagePct, 100)}%` }}
              />
            </div>
          </div>
        );
      },
    },
    {
      key: 'costUsd',
      header: '本月产生费用 (USD)',
      render: (row: TenantBillingRecord) => (
        <span className="text-xs font-bold font-mono text-emerald-600">${row.costUsd.toFixed(3)}</span>
      ),
    },
    {
      key: 'sessionsCount',
      header: '会话总数 / 自动解决率',
      render: (row: TenantBillingRecord) => (
        <div>
          <div className="text-xs text-slate-800 font-medium">{row.sessionsCount} 个会话</div>
          <div className="text-[10px] text-slate-400">Autopilot: {(row.autopilotRate * 100).toFixed(0)}%</div>
        </div>
      ),
    },
    {
      key: 'actions',
      header: '操作',
      align: 'right' as const,
      render: (row: TenantBillingRecord) => (
        <button
          type="button"
          onClick={() => handleOpenEditQuota(row)}
          className="text-xs text-slate-600 hover:text-slate-900 font-medium px-2 py-1 rounded hover:bg-slate-100 transition-colors cursor-pointer"
        >
          调整配额
        </button>
      ),
    },
  ];

  return (
    <div className="space-y-6">
      <BillingStatsSummary />

      <div className="space-y-4">
        <FilterBar
          searchQuery={searchQuery}
          onSearchChange={setSearchQuery}
          searchPlaceholder="搜索商户名、商户ID..."
          showTenantFilter={true}
          onReset={handleResetFilters}
        />

        <DataTable<TenantBillingRecord>
          columns={columns}
          data={paginatedData}
          emptyText="未检索到租户计量账单记录"
          pagination={{
            currentPage,
            pageSize,
            total,
            onPageChange: setCurrentPage,
          }}
        />
      </div>

      <QuotaFormModal
        isOpen={isEditOpen}
        onClose={() => setIsEditOpen(false)}
        onSubmit={handleSaveQuota}
        selectedItem={selectedItem}
        formData={formData}
        setFormData={setFormData}
      />
    </div>
  );
}
export default BillingPage;
