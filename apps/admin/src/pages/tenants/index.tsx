import type React from 'react';
import { useEffect, useState } from 'react';
import { ConfirmDialog, DataTable, FilterBar } from '../../components/crud';
import { useAdminCrud } from '../../hooks/useAdminCrud';
import { useAdminTenantStore } from '../../store/tenantStore';
import { TenantFormModal } from './components/TenantFormModal';
import type { TenantRecord } from './types';

export * from './types';

const INITIAL_TENANTS: TenantRecord[] = [
  {
    id: 'nike',
    name: 'Nike 官方旗舰店',
    industry: '运动服饰',
    channel: 'Web + Mobile + WeChat',
    apiKey: 'key_nike_sec_9942a',
    refundLimit: 500,
    autoEscalation: true,
    webhookUrl: 'https://api.nike.com/webhooks/agent',
    status: 'active',
    createdAt: '2026-01-10',
  },
  {
    id: 'adidas',
    name: 'Adidas 运动专营',
    industry: '运动鞋履',
    channel: 'Web Widget',
    apiKey: 'key_adi_sec_8112b',
    refundLimit: 300,
    autoEscalation: true,
    webhookUrl: 'https://spi.adidas.com/v1/approvals',
    status: 'active',
    createdAt: '2026-02-01',
  },
  {
    id: 'ecommerce',
    name: '通用电商主站 (Default)',
    industry: '综合零售',
    channel: 'All Open Channels',
    apiKey: 'key_ecom_sec_1001x',
    refundLimit: 200,
    autoEscalation: false,
    webhookUrl: 'https://internal.ecommerce.com/spi',
    status: 'active',
    createdAt: '2025-11-20',
  },
];

export function TenantsPage() {
  const { addOrUpdateTenant, removeTenant } = useAdminTenantStore();

  const {
    data,
    setData,
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
    isCreateOpen,
    setIsCreateOpen,
    isEditOpen,
    setIsEditOpen,
    selectedItem,
    setSelectedItem,
    itemToDelete,
    setItemToDelete,
    createItem,
    updateItem,
    deleteItem,
  } = useAdminCrud<TenantRecord>({
    initialData: INITIAL_TENANTS,
    storageKey: 'smartserve_admin_tenants',
    tenantKey: 'id' as keyof TenantRecord,
    filterFn: (item, query, status) => {
      if (status && item.status !== status) return false;
      if (query.trim()) {
        const q = query.toLowerCase();
        return (
          item.id.toLowerCase().includes(q) ||
          item.name.toLowerCase().includes(q) ||
          item.industry.toLowerCase().includes(q)
        );
      }
      return true;
    },
    onItemCreated: (item) => {
      addOrUpdateTenant({
        id: item.id,
        name: item.name,
        badgeColor: 'bg-emerald-50 text-emerald-700 border-emerald-200',
      });
      // 异步尝试同步至服务端
      fetch('/api/tenant', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(item),
      }).catch(() => {});
    },
    onItemUpdated: (item) => {
      addOrUpdateTenant({
        id: item.id,
        name: item.name,
        badgeColor: 'bg-blue-50 text-blue-700 border-blue-200',
      });
      fetch('/api/tenant', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(item),
      }).catch(() => {});
    },
    onItemDeleted: (id) => {
      removeTenant(id);
      fetch(`/api/tenant/${id}`, {
        method: 'DELETE',
      }).catch(() => {});
    },
  });

  // 页面挂载时尝试拉取服务端已注册租户列表进行合并
  useEffect(() => {
    let isMounted = true;
    fetch('/api/tenant/list')
      .then((res) => res.json())
      .then((res) => {
        if (!isMounted || !res || !res.success || !Array.isArray(res.tenants)) return;
        setData((prev) => {
          const merged = [...prev];
          for (const sTenant of res.tenants) {
            const idx = merged.findIndex((t) => t.id.toLowerCase() === sTenant.id.toLowerCase());
            if (idx >= 0) {
              merged[idx] = { ...merged[idx], ...sTenant };
            } else {
              merged.push(sTenant);
            }
            addOrUpdateTenant({
              id: sTenant.id,
              name: sTenant.name,
              badgeColor: 'bg-indigo-50 text-indigo-700 border-indigo-200',
            });
          }
          if (typeof window !== 'undefined') {
            try {
              localStorage.setItem('smartserve_admin_tenants', JSON.stringify(merged));
            } catch {}
          }
          return merged;
        });
      })
      .catch(() => {});

    return () => {
      isMounted = false;
    };
  }, [setData, addOrUpdateTenant]);

  const [formData, setFormData] = useState<Partial<TenantRecord>>({});

  const handleOpenCreate = () => {
    setFormData({
      id: '',
      name: '',
      industry: '综合电商',
      channel: 'Web Widget',
      apiKey: `key_${Date.now().toString(36)}`,
      refundLimit: 300,
      autoEscalation: true,
      webhookUrl: 'https://api.example.com/spi/webhook',
      status: 'active',
    });
    setIsCreateOpen(true);
  };

  const handleOpenEdit = (tenant: TenantRecord) => {
    setSelectedItem(tenant);
    setFormData({ ...tenant });
    setIsEditOpen(true);
  };

  const handleSaveSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (isCreateOpen) {
      if (!formData.id || !formData.name) return;
      createItem({
        ...(formData as TenantRecord),
        createdAt: new Date().toISOString().split('T')[0],
      });
    } else if (isEditOpen && selectedItem) {
      updateItem('id', {
        ...selectedItem,
        ...(formData as TenantRecord),
      });
    }
  };

  const columns = [
    {
      key: 'name',
      header: '商户名称 / ID',
      render: (row: TenantRecord) => (
        <div>
          <div className="font-semibold text-slate-900">{row.name}</div>
          <div className="text-xs font-mono text-slate-400">ID: {row.id}</div>
        </div>
      ),
    },
    {
      key: 'industry',
      header: '行业 / 接入渠道',
      render: (row: TenantRecord) => (
        <div>
          <span className="inline-flex items-center px-2 py-0.5 rounded text-[11px] font-medium bg-slate-100 text-slate-700">
            {row.industry}
          </span>
          <div className="text-xs text-slate-400 mt-0.5">{row.channel}</div>
        </div>
      ),
    },
    {
      key: 'apiKey',
      header: 'API Key / SPI Webhook',
      render: (row: TenantRecord) => (
        <div>
          <div className="text-xs font-mono text-slate-600 bg-slate-50 px-2 py-0.5 rounded border border-slate-200 inline-block">
            {row.apiKey}
          </div>
          <div className="text-[11px] text-slate-400 truncate max-w-xs mt-0.5">{row.webhookUrl}</div>
        </div>
      ),
    },
    {
      key: 'refundLimit',
      header: '风控阈值 (退款)',
      render: (row: TenantRecord) => <span className="font-semibold text-slate-800">¥{row.refundLimit}</span>,
    },
    {
      key: 'status',
      header: '状态',
      render: (row: TenantRecord) => (
        <span
          className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${
            row.status === 'active'
              ? 'bg-emerald-50 text-emerald-700 border border-emerald-200'
              : 'bg-slate-100 text-slate-500 border border-slate-200'
          }`}
        >
          {row.status === 'active' ? '正常运行' : '已停用'}
        </span>
      ),
    },
    {
      key: 'actions',
      header: '操作',
      align: 'right' as const,
      render: (row: TenantRecord) => (
        <div className="flex items-center justify-end gap-2" onClick={(e) => e.stopPropagation()}>
          <button
            type="button"
            onClick={() => handleOpenEdit(row)}
            className="text-xs text-slate-600 hover:text-slate-900 font-medium px-2 py-1 rounded hover:bg-slate-100 transition-colors cursor-pointer"
          >
            编辑配置
          </button>
          <button
            type="button"
            onClick={() => setItemToDelete(row)}
            className="text-xs text-rose-600 hover:text-rose-800 font-medium px-2 py-1 rounded hover:bg-rose-50 transition-colors cursor-pointer"
          >
            删除
          </button>
        </div>
      ),
    },
  ];

  return (
    <div className="space-y-4">
      <FilterBar
        searchQuery={searchQuery}
        onSearchChange={setSearchQuery}
        searchPlaceholder="搜索商户名、商户ID、行业..."
        statusFilter={statusFilter}
        onStatusChange={setStatusFilter}
        statusOptions={[
          { label: '正常运行', value: 'active' },
          { label: '已停用', value: 'disabled' },
        ]}
        showTenantFilter={false}
        onReset={handleResetFilters}
        actions={
          <button
            type="button"
            onClick={handleOpenCreate}
            className="px-3.5 py-1.5 text-xs font-medium bg-slate-900 hover:bg-slate-800 text-white rounded-lg transition-colors shadow-xs flex items-center gap-1.5 cursor-pointer"
          >
            <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
            </svg>
            新增商户入驻
          </button>
        }
      />

      <DataTable<TenantRecord>
        columns={columns}
        data={paginatedData}
        emptyText="未检索到符合条件的商户租户"
        pagination={{
          currentPage,
          pageSize,
          total,
          onPageChange: setCurrentPage,
        }}
      />

      <TenantFormModal
        isOpen={isCreateOpen || isEditOpen}
        onClose={() => {
          setIsCreateOpen(false);
          setIsEditOpen(false);
        }}
        onSubmit={handleSaveSubmit}
        isCreate={isCreateOpen}
        formData={formData}
        setFormData={setFormData}
      />

      <ConfirmDialog
        isOpen={Boolean(itemToDelete)}
        onClose={() => setItemToDelete(null)}
        onConfirm={() => itemToDelete && deleteItem('id', itemToDelete.id)}
        title="确认删除该商户租户？"
        description={`删除商户 [${itemToDelete?.name}] 后，该租户下的所有 API 调用与 Webhook 回调将被注销且不可恢复。`}
        confirmText="确认删除"
      />
    </div>
  );
}

export default TenantsPage;
