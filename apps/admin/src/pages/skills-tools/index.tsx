import React, { useCallback, useState } from 'react';
import { DataTable, FilterBar } from '../../components/crud';
import { useAdminCrud } from '../../hooks/useAdminCrud';
import { skillsApi } from '../../lib/api';
import { ToolFormModal } from './components/ToolFormModal';
import type { SkillToolRecord } from './types';

export * from './types';

export function SkillsToolsPage() {
  const fetchSkillsList = useCallback(async ({ tenantId }: { tenantId: string }) => {
    try {
      const res = await skillsApi.getConfig(tenantId === 'all' ? 'ecommerce' : tenantId);
      if (res.success && Array.isArray(res.skills)) {
        const remoteSkills: SkillToolRecord[] = res.skills.map((s: any) => ({
          id: s.id,
          name: s.name || s.id,
          type: 'skill',
          description: s.description || 'SOP 业务技能',
          riskLevel: s.requiresApproval ? 'high' : 'low',
          requiresHitl: Boolean(s.requiresApproval),
          tenantScope: tenantId,
          status: s.enabled ? 'enabled' : 'disabled',
          approvalThresholdAmount: s.approvalThresholdAmount,
        }));

        return remoteSkills;
      }
    } catch (err) {
      console.warn('Failed to fetch remote skills:', err);
    }
    return [];
  }, []);

  const updateSkillApi = useCallback(async (tool: SkillToolRecord, tenantId: string) => {
    if (tool.type === 'skill') {
      await skillsApi.updateConfig(tenantId === 'all' ? 'ecommerce' : tenantId, tool.id, {
        enabled: tool.status === 'enabled',
        approvalThresholdAmount: tool.approvalThresholdAmount,
      });
    }
    return tool;
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
    updateItem,
  } = useAdminCrud<SkillToolRecord>({
    fetchList: fetchSkillsList,
    updateApi: updateSkillApi,
    tenantKey: 'tenantScope' as keyof SkillToolRecord,
    filterFn: (item, query, type) => {
      if (type && item.type !== type) return false;
      if (query.trim()) {
        const q = query.toLowerCase();
        return (
          item.id.toLowerCase().includes(q) ||
          item.name.toLowerCase().includes(q) ||
          item.description.toLowerCase().includes(q)
        );
      }
      return true;
    },
  });

  const [formData, setFormData] = useState<Partial<SkillToolRecord>>({});

  // Skills 由引擎代码注册表定义(SkillRegistry),控制台仅支持配置编辑(启用/阈值),
  // 不提供创建与注销 —— 此前的本地假创建/假删除在刷新后即回滚,已移除。

  const handleOpenEdit = (tool: SkillToolRecord) => {
    setFormData({ ...tool });
    setIsEditOpen(true);
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (isEditOpen && formData.id) {
      updateItem('id', formData as SkillToolRecord);
    }
  };

  const columns = [
    {
      key: 'id',
      header: '工具标识 / 名称',
      render: (row: SkillToolRecord) => (
        <div>
          <div className="font-semibold text-slate-900 text-xs font-mono">{row.id}</div>
          <div className="text-xs text-slate-600 font-medium">{row.name}</div>
        </div>
      ),
    },
    {
      key: 'type',
      header: '工具类型',
      render: (row: SkillToolRecord) => {
        const typeMap = {
          native: {
            label: 'Native 原生',
            cls: 'bg-slate-100 text-slate-700 border-slate-200',
          },
          openapi: {
            label: 'OpenAPI 协议',
            cls: 'bg-blue-50 text-blue-700 border-blue-200',
          },
          mcp: {
            label: 'MCP Server',
            cls: 'bg-purple-50 text-purple-700 border-purple-200',
          },
          skill: {
            label: 'SOP Skill 技能',
            cls: 'bg-amber-50 text-amber-700 border-amber-200',
          },
        };
        const t = typeMap[row.type] || typeMap.native;
        return (
          <span className={`inline-flex items-center px-2 py-0.5 rounded text-[11px] font-medium border ${t.cls}`}>
            {t.label}
          </span>
        );
      },
    },
    {
      key: 'description',
      header: '工具功能描述',
      render: (row: SkillToolRecord) => (
        <div className="text-xs text-slate-600 truncate max-w-sm">{row.description}</div>
      ),
    },
    {
      key: 'riskLevel',
      header: '风控等级 / HITL',
      render: (row: SkillToolRecord) => (
        <div className="flex items-center gap-1.5">
          <span
            className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${
              row.riskLevel === 'high'
                ? 'bg-rose-100 text-rose-800'
                : row.riskLevel === 'medium'
                  ? 'bg-amber-100 text-amber-800'
                  : 'bg-emerald-100 text-emerald-800'
            }`}
          >
            {row.riskLevel.toUpperCase()}
          </span>
          {row.requiresHitl && (
            <span className="px-1.5 py-0.5 text-[10px] font-semibold bg-rose-50 text-rose-600 border border-rose-200 rounded">
              强制人工核准
            </span>
          )}
        </div>
      ),
    },
    {
      key: 'tenantScope',
      header: '适用租户范围',
      render: (row: SkillToolRecord) => (
        <span className="text-xs font-mono font-medium text-slate-700">
          {row.tenantScope === 'all' ? '全平台通用' : row.tenantScope.toUpperCase()}
        </span>
      ),
    },
    {
      key: 'status',
      header: '状态',
      render: (row: SkillToolRecord) => (
        <span
          className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${
            row.status === 'enabled'
              ? 'bg-emerald-50 text-emerald-700 border border-emerald-200'
              : 'bg-slate-100 text-slate-500 border border-slate-200'
          }`}
        >
          {row.status === 'enabled' ? '已启用' : '已禁用'}
        </span>
      ),
    },
    {
      key: 'actions',
      header: '操作',
      align: 'right' as const,
      render: (row: SkillToolRecord) => (
        <div className="flex items-center justify-end gap-2">
          <button
            type="button"
            onClick={() => handleOpenEdit(row)}
            className="text-xs text-slate-600 hover:text-slate-900 font-medium px-2 py-1 rounded hover:bg-slate-100 transition-colors cursor-pointer"
          >
            配置
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
        searchPlaceholder="搜索工具名称、标识或描述..."
        statusFilter={statusFilter}
        onStatusChange={setStatusFilter}
        statusOptions={[
          { label: 'SOP Skill 技能', value: 'skill' },
          { label: '原生工具 (Native)', value: 'native' },
          { label: 'OpenAPI 协议', value: 'openapi' },
          { label: 'MCP Server', value: 'mcp' },
        ]}
        onReset={handleResetFilters}
      />

      <DataTable<SkillToolRecord>
        columns={columns}
        data={paginatedData}
        emptyText="未检索到匹配的工具/技能"
        pagination={{
          currentPage,
          pageSize,
          total,
          onPageChange: setCurrentPage,
        }}
      />

      <ToolFormModal
        isOpen={isEditOpen}
        onClose={() => {
          setIsEditOpen(false);
        }}
        onSubmit={handleSubmit}
        isCreate={false}
        formData={formData}
        setFormData={setFormData}
      />
    </div>
  );
}
export default SkillsToolsPage;
