import React, { useCallback, useEffect, useRef, useState } from 'react';
import { DataTable, FilterBar } from '../../components/crud';
import { useAdminCrud } from '../../hooks/useAdminCrud';
import { billingApi } from '../../lib/api';
import { BillingStatsSummary } from './components/BillingStatsSummary';
import { CreditsAdjustModal } from './components/CreditsAdjustModal';
import { CreditsDetailModal } from './components/CreditsDetailModal';
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

  // ---- 积分池(2026-10-21 用量配额闸)----
  // 余额按行懒取(进页 N 次 GET 换真余额);undefined = 未取/未知「—」,
  // null = 服务端明示未开通「未开通」,严禁编 0。
  const [balances, setBalances] = useState<Record<string, number | null>>({});
  const balanceRequestedRef = useRef<Set<string>>(new Set());
  const [adjustTarget, setAdjustTarget] = useState<TenantBillingRecord | null>(null);
  const [detailTarget, setDetailTarget] = useState<TenantBillingRecord | null>(null);

  const loadBalance = useCallback(async (businessId: string) => {
    balanceRequestedRef.current.add(businessId);
    try {
      const res = await billingApi.getCredits(businessId);
      if (res.success && res.data) {
        const balance = res.data.balance ?? null;
        setBalances((prev) => ({ ...prev, [businessId]: balance }));
      }
    } catch {
      // 传输失败保持「—」未知态,不编造
    }
  }, []);

  useEffect(() => {
    for (const row of paginatedData) {
      if (!balanceRequestedRef.current.has(row.businessId)) void loadBalance(row.businessId);
    }
  }, [paginatedData, loadBalance]);

  const handleCreditsAdjusted = useCallback((businessId: string, balance: number | null) => {
    setBalances((prev) => ({ ...prev, [businessId]: balance }));
  }, []);

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
      key: 'credits',
      header: '积分余额(共享池)',
      render: (row: TenantBillingRecord) => {
        const v = balances[row.businessId];
        if (v === null) {
          return <span className="text-xs text-slate-400">未开通</span>;
        }
        if (v === undefined) {
          return <span className="text-xs text-slate-300">—</span>;
        }
        return (
          <span className="text-xs font-bold font-mono tabular-nums text-slate-800">{v.toLocaleString()}</span>
        );
      },
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
        <div className="flex items-center justify-end gap-1">
          <button
            type="button"
            onClick={() => handleOpenEditQuota(row)}
            className="text-xs text-slate-600 hover:text-slate-900 font-medium px-2 py-1 rounded hover:bg-slate-100 transition-colors cursor-pointer"
          >
            调整配额
          </button>
          <button
            type="button"
            onClick={() => setAdjustTarget(row)}
            className="text-xs text-slate-600 hover:text-slate-900 font-medium px-2 py-1 rounded hover:bg-slate-100 transition-colors cursor-pointer"
          >
            调整积分
          </button>
          <button
            type="button"
            onClick={() => setDetailTarget(row)}
            className="text-xs text-slate-600 hover:text-slate-900 font-medium px-2 py-1 rounded hover:bg-slate-100 transition-colors cursor-pointer"
          >
            积分流水
          </button>
        </div>
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

      <CreditsAdjustModal
        isOpen={!!adjustTarget}
        onClose={() => setAdjustTarget(null)}
        record={adjustTarget}
        onSuccess={handleCreditsAdjusted}
      />

      <CreditsDetailModal isOpen={!!detailTarget} onClose={() => setDetailTarget(null)} record={detailTarget} />
    </div>
  );
}
export default BillingPage;
