import React, { useCallback, useState } from 'react';
import { ConfirmDialog, DataTable, FilterBar } from '../../components/crud';
import { useAdminCrud } from '../../hooks/useAdminCrud';
import { guardrailsApi } from '../../lib/api';
import { GuardrailFormModal } from './components/GuardrailFormModal';
import type { GuardrailRuleRecord } from './types';

export * from './types';

export function GuardrailsPage() {
  const fetchGuardrailsList = useCallback(async ({ tenantId }: { tenantId: string }) => {
    try {
      const res = await guardrailsApi.list(tenantId === 'all' ? undefined : tenantId);
      if (res.success && Array.isArray(res.data)) {
        return res.data;
      }
    } catch (err) {
      console.warn('Failed to fetch remote guardrails:', err);
    }
    return [];
  }, []);

  const createGuardrailApi = useCallback(async (item: Partial<GuardrailRuleRecord>, tenantId: string) => {
    const res = await guardrailsApi.create(
      {
        ruleName: item.ruleName,
        ruleType: item.ruleType,
        pattern: item.pattern,
        action: item.action,
        severity: item.severity,
        isEnabled: item.isEnabled,
      },
      tenantId,
    );
    return res.data || item;
  }, []);

  const updateGuardrailApi = useCallback(async (item: GuardrailRuleRecord, tenantId: string) => {
    const res = await guardrailsApi.update(item.id, item, tenantId);
    return res.data || item;
  }, []);

  const deleteGuardrailApi = useCallback(async (id: string, tenantId: string) => {
    await guardrailsApi.delete(id, tenantId);
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
  } = useAdminCrud<GuardrailRuleRecord>({
    fetchList: fetchGuardrailsList,
    createApi: createGuardrailApi,
    updateApi: updateGuardrailApi,
    deleteApi: deleteGuardrailApi,
    filterFn: (item, query, type) => {
      if (type && item.ruleType !== type) return false;
      if (query.trim()) {
        const q = query.toLowerCase();
        return (
          item.ruleName.toLowerCase().includes(q) ||
          item.pattern.toLowerCase().includes(q) ||
          item.id.toLowerCase().includes(q)
        );
      }
      return true;
    },
  });

  const [formData, setFormData] = useState<Partial<GuardrailRuleRecord>>({});

  const handleOpenCreate = () => {
    setFormData({
      id: `gr_${Date.now()}`,
      ruleName: '',
      ruleType: 'sensitive_keyword',
      pattern: '',
      action: 'block',
      severity: 'high',
      isEnabled: true,
    });
    setIsCreateOpen(true);
  };

  const handleOpenEdit = (rule: GuardrailRuleRecord) => {
    setFormData({ ...rule });
    setIsEditOpen(true);
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (isCreateOpen) {
      if (!formData.ruleName || !formData.pattern) return;
      createItem({
        ...(formData as GuardrailRuleRecord),
        updatedAt: new Date().toISOString().split('T')[0],
      });
    } else if (isEditOpen && formData.id) {
      updateItem('id', {
        ...(formData as GuardrailRuleRecord),
        updatedAt: new Date().toISOString().split('T')[0],
      });
    }
  };

  const columns = [
    {
      key: 'ruleName',
      header: '规则名称 / 标识',
      render: (row: GuardrailRuleRecord) => (
        <div>
          <div className="font-semibold text-slate-900 text-xs">{row.ruleName}</div>
          <div className="text-xs text-slate-400 font-mono">ID: {row.id}</div>
        </div>
      ),
    },
    {
      key: 'ruleType',
      header: '防护类型',
      render: (row: GuardrailRuleRecord) => (
        <span className="text-xs font-medium bg-slate-100 text-slate-700 px-2 py-0.5 rounded">{row.ruleType}</span>
      ),
    },
    {
      key: 'pattern',
      header: '匹配规则 / 正则特征',
      render: (row: GuardrailRuleRecord) => (
        <span className="text-xs font-mono bg-slate-50 text-slate-700 px-2 py-0.5 rounded border border-slate-200">
          {row.pattern}
        </span>
      ),
    },
    {
      key: 'action',
      header: '拦截响应动作',
      render: (row: GuardrailRuleRecord) => {
        const actionMap = {
          block: {
            label: '直接拦截 (Block)',
            cls: 'bg-rose-50 text-rose-700 border-rose-200',
          },
          mask: {
            label: '脱敏替换 (Mask)',
            cls: 'bg-amber-50 text-amber-700 border-amber-200',
          },
          warn: {
            label: '安全告警 (Warn)',
            cls: 'bg-blue-50 text-blue-700 border-blue-200',
          },
          escalate_hitl: {
            label: '升级人工 (HITL)',
            cls: 'bg-purple-50 text-purple-700 border-purple-200',
          },
        };
        const act = actionMap[row.action] || actionMap.block;
        return (
          <span className={`inline-flex items-center px-2 py-0.5 rounded text-[11px] font-medium border ${act.cls}`}>
            {act.label}
          </span>
        );
      },
    },
    {
      key: 'isEnabled',
      header: '启用状态',
      render: (row: GuardrailRuleRecord) => (
        <span
          className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${
            row.isEnabled
              ? 'bg-emerald-50 text-emerald-700 border border-emerald-200'
              : 'bg-slate-100 text-slate-500 border border-slate-200'
          }`}
        >
          {row.isEnabled ? '已启用' : '已停用'}
        </span>
      ),
    },
    {
      key: 'actions',
      header: '操作',
      align: 'right' as const,
      render: (row: GuardrailRuleRecord) => (
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
        searchPlaceholder="搜索安全规则名称、正则特征..."
        statusFilter={statusFilter}
        onStatusChange={setStatusFilter}
        statusOptions={[
          { label: '敏感词/隐私', value: 'sensitive_keyword' },
          { label: 'SQL 注入防御', value: 'sql_injection' },
          { label: '提示词防泄露', value: 'prompt_leakage' },
        ]}
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
            添加安全围栏规则
          </button>
        }
      />

      <DataTable<GuardrailRuleRecord>
        columns={columns}
        data={paginatedData}
        emptyText="未检索到安全合规围栏规则"
        pagination={{
          currentPage,
          pageSize,
          total,
          onPageChange: setCurrentPage,
        }}
      />

      <GuardrailFormModal
        isOpen={isCreateOpen || isEditOpen}
        onClose={() => {
          setIsCreateOpen(false);
          setIsEditOpen(false);
        }}
        onSubmit={handleSubmit}
        isCreate={isCreateOpen}
        selectedItem={selectedItem}
        formData={formData}
        setFormData={setFormData}
      />

      <ConfirmDialog
        isOpen={Boolean(itemToDelete)}
        onClose={() => setItemToDelete(null)}
        onConfirm={() => itemToDelete && deleteItem('id', itemToDelete.id)}
        title="确认删除该安全合规规则？"
        description={`删除规则 [${itemToDelete?.ruleName}] 后，系统将不再对此类输入特征进行拦截或脱敏。`}
        confirmText="确认删除"
      />
    </div>
  );
}
export default GuardrailsPage;
