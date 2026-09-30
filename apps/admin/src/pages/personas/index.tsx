import React, { useCallback, useMemo, useState } from 'react';
import { ConfirmDialog, DataTable, FilterBar } from '../../components/crud';
import { useAdminCrud } from '../../hooks/useAdminCrud';
import { personasApi } from '../../lib/api';
import { useAdminTenantStore } from '../../store/tenantStore';
import { PersonaFormModal } from './components/PersonaFormModal';
import type { PersonaRecord } from './types';

export * from './types';

export function PersonasPage() {
  const { selectedTenantId } = useAdminTenantStore();
  // 具名租户视图的 global 画像只读附带(persona-hardening 05,与坐席台同口径):
  // 平台视角(all)全量可管;具名租户只能变更本租户 tenant 行,global 行读得到改不了
  const canMutateRow = useCallback(
    (row: PersonaRecord) =>
      selectedTenantId === 'all' || (row.scope !== 'global' && row.businessId === selectedTenantId),
    [selectedTenantId],
  );

  const fetchPersonasList = useCallback(async ({ tenantId }: { tenantId: string }) => {
    try {
      const res = await personasApi.list(tenantId === 'all' ? undefined : tenantId);
      if (res.success && Array.isArray(res.data)) {
        return res.data;
      }
    } catch (err) {
      console.warn('Failed to fetch remote personas:', err);
    }
    return [];
  }, []);

  const createPersonaApi = useCallback(async (item: Partial<PersonaRecord>, tenantId: string) => {
    const res = await personasApi.create(item, tenantId);
    return res.data || item;
  }, []);

  const updatePersonaApi = useCallback(async (item: PersonaRecord, tenantId: string) => {
    const res = await personasApi.update(item.id, item, tenantId);
    return res.data || item;
  }, []);

  const deletePersonaApi = useCallback(async (id: string, tenantId: string) => {
    await personasApi.delete(id, tenantId);
    return true;
  }, []);

  const {
    data,
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
    itemToDelete,
    setItemToDelete,
    createItem,
    updateItem,
    deleteItem,
    error,
  } = useAdminCrud<PersonaRecord>({
    fetchList: fetchPersonasList,
    createApi: createPersonaApi,
    updateApi: updatePersonaApi,
    deleteApi: deletePersonaApi,
    tenantKey: 'businessId' as keyof PersonaRecord,
    filterFn: (item, query, status, tenantId) => {
      // global 画像在具名租户视图只读附带(网关已附带返回),不在客户端再筛掉
      if (tenantId !== 'all' && item.businessId !== tenantId && item.scope !== 'global') return false;
      if (status && item.status !== status) return false;
      if (query.trim()) {
        const q = query.toLowerCase();
        return (
          item.userId.toLowerCase().includes(q) ||
          item.fact.toLowerCase().includes(q) ||
          item.source.toLowerCase().includes(q)
        );
      }
      return true;
    },
  });

  const [formData, setFormData] = useState<Partial<PersonaRecord>>({});

  // 待审闭环(persona-hardening 05):中置信抽取落 pending,召回侧不消费,
  // 唯一翻案通道在此 —— 计数角标 + 一键批/驳(updateItem 走既有 PUT 通道)
  const pendingCount = useMemo(() => data.filter((r) => r.status === 'pending').length, [data]);

  const reviewItem = useCallback(
    (row: PersonaRecord, status: 'approved' | 'rejected') => {
      updateItem('id', { ...row, status });
    },
    [updateItem],
  );

  const handleOpenCreate = () => {
    setFormData({
      id: `fact_${Date.now()}`,
      userId: '',
      businessId: 'ecommerce',
      fact: '',
      confidence: 0.9,
      source: 'admin_manual_input',
      status: 'approved',
    });
    setIsCreateOpen(true);
  };

  const handleOpenEdit = (fact: PersonaRecord) => {
    setFormData({ ...fact });
    setIsEditOpen(true);
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (isCreateOpen) {
      if (!formData.userId || !formData.fact) return;
      createItem({
        ...(formData as PersonaRecord),
        createdAt: new Date().toISOString().split('T')[0],
      });
    } else if (isEditOpen && formData.id) {
      updateItem('id', formData as PersonaRecord);
    }
  };

  const columns = [
    {
      key: 'userId',
      header: '用户 ID / 租户',
      render: (row: PersonaRecord) => (
        <div>
          <div className="font-semibold text-slate-900 font-mono text-xs">{row.userId}</div>
          <span
            className={`inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium mt-0.5 ${
              row.businessId === 'nike'
                ? 'bg-rose-50 text-rose-700'
                : row.businessId === 'adidas'
                  ? 'bg-blue-50 text-blue-700'
                  : 'bg-amber-50 text-amber-700'
            }`}
          >
            {row.businessId.toUpperCase()}
          </span>
          {row.scope === 'global' && (
            <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium mt-0.5 ml-1 bg-slate-100 text-slate-600 border border-slate-200">
              全局可见
            </span>
          )}
        </div>
      ),
    },
    {
      key: 'fact',
      header: '长程事实记忆内容 (Persona Fact)',
      render: (row: PersonaRecord) => (
        <div className="text-xs text-slate-800 leading-relaxed max-w-xl font-medium">{row.fact}</div>
      ),
    },
    {
      key: 'confidence',
      header: '置信度 / 来源',
      render: (row: PersonaRecord) => (
        <div>
          <div className="text-xs font-semibold text-slate-800">{(row.confidence * 100).toFixed(0)}%</div>
          <div className="text-[10px] text-slate-400 font-mono">{row.source}</div>
        </div>
      ),
    },
    {
      key: 'status',
      header: '状态',
      render: (row: PersonaRecord) => {
        const map = {
          approved: {
            label: '已生效',
            cls: 'bg-emerald-50 text-emerald-700 border-emerald-200',
          },
          pending: {
            label: '待核实',
            cls: 'bg-amber-50 text-amber-700 border-amber-200',
          },
          rejected: {
            label: '已废弃',
            cls: 'bg-slate-100 text-slate-500 border-slate-200',
          },
        };
        const st = map[row.status] || map.approved;
        return (
          <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium border ${st.cls}`}>
            {st.label}
          </span>
        );
      },
    },
    {
      key: 'createdAt',
      header: '记录时间',
      render: (row: PersonaRecord) => <span className="text-xs text-slate-400 font-mono">{row.createdAt}</span>,
    },
    {
      key: 'actions',
      header: '操作',
      align: 'right' as const,
      render: (row: PersonaRecord) => {
        const mutable = canMutateRow(row);
        const lockTitle = mutable ? undefined : 'global 画像全员可见,由平台视角(tenantId=all)管理';
        return (
          <div className="flex items-center justify-end gap-2">
            {row.status === 'pending' && (
              <>
                <button
                  type="button"
                  disabled={!mutable}
                  title={lockTitle ?? '批复生效:该画像将参与召回'}
                  onClick={() => reviewItem(row, 'approved')}
                  className="text-xs text-emerald-600 hover:text-emerald-800 font-medium px-2 py-1 rounded hover:bg-emerald-50 transition-colors cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:bg-transparent"
                >
                  批准
                </button>
                <button
                  type="button"
                  disabled={!mutable}
                  title={lockTitle ?? '驳回:该画像永不参与召回'}
                  onClick={() => reviewItem(row, 'rejected')}
                  className="text-xs text-slate-500 hover:text-slate-700 font-medium px-2 py-1 rounded hover:bg-slate-100 transition-colors cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:bg-transparent"
                >
                  驳回
                </button>
              </>
            )}
            <button
              type="button"
              disabled={!mutable}
              title={lockTitle}
              onClick={() => handleOpenEdit(row)}
              className="text-xs text-slate-600 hover:text-slate-900 font-medium px-2 py-1 rounded hover:bg-slate-100 transition-colors cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:bg-transparent"
            >
              编辑
            </button>
            <button
              type="button"
              disabled={!mutable}
              title={lockTitle}
              onClick={() => setItemToDelete(row)}
              className="text-xs text-rose-600 hover:text-rose-800 font-medium px-2 py-1 rounded hover:bg-rose-50 transition-colors cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:bg-transparent"
            >
              废弃删除
            </button>
          </div>
        );
      },
    },
  ];

  return (
    <div className="space-y-4">
      {pendingCount > 0 && (
        <button
          type="button"
          onClick={() => setStatusFilter('pending')}
          className="w-full flex items-center justify-between px-4 py-2.5 rounded-lg border border-amber-200 bg-amber-50 hover:bg-amber-100 transition-colors cursor-pointer text-left"
        >
          <span className="text-xs font-medium text-amber-800">
            ⏳ 有 <span className="font-bold">{pendingCount}</span> 条待核实画像等待审核 ——
            中置信抽取不参与召回,需人工批复生效或驳回
          </span>
          <span className="text-xs font-semibold text-amber-700 shrink-0 ml-3">去审核 →</span>
        </button>
      )}
      <FilterBar
        searchQuery={searchQuery}
        onSearchChange={setSearchQuery}
        searchPlaceholder="搜索用户ID、画像事实、来源渠道..."
        statusFilter={statusFilter}
        onStatusChange={setStatusFilter}
        statusOptions={[
          { label: '已生效 (Approved)', value: 'approved' },
          { label: `待核实 (Pending)${pendingCount > 0 ? ` · ${pendingCount}` : ''}`, value: 'pending' },
          { label: '已废弃 (Rejected)', value: 'rejected' },
        ]}
        showTenantFilter={true}
        onReset={handleResetFilters}
        actions={
          <button
            type="button"
            onClick={handleOpenCreate}
            className="px-3.5 py-1.5 text-xs font-medium bg-slate-900 hover:bg-slate-800 text-white rounded-lg transition-colors shadow-xs flex items-center gap-1.5 cursor-pointer"
          >
            <svg aria-hidden="true" className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
            </svg>
            录入画像事实
          </button>
        }
      />

      <DataTable<PersonaRecord>
        columns={columns}
        data={paginatedData}
        emptyText="未检索到用户画像记忆事实"
        pagination={{
          currentPage,
          pageSize,
          total,
          onPageChange: setCurrentPage,
        }}
      />

      <PersonaFormModal
        errorMessage={error}
        isOpen={isCreateOpen || isEditOpen}
        onClose={() => {
          setIsCreateOpen(false);
          setIsEditOpen(false);
        }}
        onSubmit={handleSubmit}
        isCreate={isCreateOpen}
        formData={formData}
        setFormData={setFormData}
      />

      <ConfirmDialog
        isOpen={Boolean(itemToDelete)}
        onClose={() => setItemToDelete(null)}
        onConfirm={() => itemToDelete && deleteItem('id', itemToDelete.id)}
        title="确认废弃并删除该画像事实？"
        description={`删除后，Agent 将不再向该用户注入该条偏好记忆（${itemToDelete?.fact?.slice(0, 30)}...）。`}
        confirmText="确认删除"
      />
    </div>
  );
}
export default PersonasPage;
