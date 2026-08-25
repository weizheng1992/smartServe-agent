import React, { useCallback, useState } from 'react';
import { ConfirmDialog, DataTable, FilterBar } from '../../components/crud';
import { useAdminCrud } from '../../hooks/useAdminCrud';
import { personasApi } from '../../lib/api';
import { PersonaFormModal } from './components/PersonaFormModal';
import type { PersonaRecord } from './types';

export * from './types';

const INITIAL_PERSONAS: PersonaRecord[] = [
  {
    id: 'fact_001',
    userId: 'u_vip_881',
    businessId: 'nike',
    fact: '跑鞋鞋码偏好 42.5 码，通常在周末上午进行半马训练',
    confidence: 0.96,
    source: 'chat_dialogue_inference',
    status: 'approved',
    createdAt: '2026-02-20',
  },
  {
    id: 'fact_002',
    userId: 'u_user_332',
    businessId: 'adidas',
    fact: '偏好三叶草复古休闲系列，对环保再生材质有强烈认同感',
    confidence: 0.88,
    source: 'explicit_user_statement',
    status: 'approved',
    createdAt: '2026-02-21',
  },
  {
    id: 'fact_003',
    userId: 'u_runner_102',
    businessId: 'nike',
    fact: '对快递时效要求极高，通常要求顺丰次日达发货',
    confidence: 0.92,
    source: 'chat_dialogue_inference',
    status: 'pending',
    createdAt: '2026-02-22',
  },
];

export function PersonasPage() {
  const fetchPersonasList = useCallback(async ({ tenantId }: { tenantId: string }) => {
    try {
      const res = await personasApi.list(tenantId === 'all' ? undefined : tenantId);
      if (res.success && Array.isArray(res.data)) {
        return res.data;
      }
    } catch (err) {
      console.warn('Failed to fetch remote personas:', err);
    }
    return INITIAL_PERSONAS;
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
  } = useAdminCrud<PersonaRecord>({
    initialData: INITIAL_PERSONAS,
    fetchList: fetchPersonasList,
    createApi: createPersonaApi,
    updateApi: updatePersonaApi,
    deleteApi: deletePersonaApi,
    tenantKey: 'businessId' as keyof PersonaRecord,
    filterFn: (item, query, status, tenantId) => {
      if (tenantId !== 'all' && item.businessId !== tenantId) return false;
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

  const handleOpenCreate = () => {
    setFormData({
      id: `fact_${Date.now()}`,
      userId: '',
      businessId: 'nike',
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
      render: (row: PersonaRecord) => (
        <div className="flex items-center justify-end gap-2">
          <button
            type="button"
            onClick={() => handleOpenEdit(row)}
            className="text-xs text-slate-600 hover:text-slate-900 font-medium px-2 py-1 rounded hover:bg-slate-100 transition-colors cursor-pointer"
          >
            编辑
          </button>
          <button
            type="button"
            onClick={() => setItemToDelete(row)}
            className="text-xs text-rose-600 hover:text-rose-800 font-medium px-2 py-1 rounded hover:bg-rose-50 transition-colors cursor-pointer"
          >
            废弃删除
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
        searchPlaceholder="搜索用户ID、画像事实、来源渠道..."
        statusFilter={statusFilter}
        onStatusChange={setStatusFilter}
        statusOptions={[
          { label: '已生效 (Approved)', value: 'approved' },
          { label: '待核实 (Pending)', value: 'pending' },
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
            <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
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
