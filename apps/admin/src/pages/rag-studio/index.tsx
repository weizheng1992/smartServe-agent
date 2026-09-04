import React, { useCallback, useState } from 'react';
import { ConfirmDialog, DataTable, FilterBar } from '../../components/crud';
import { useAdminCrud } from '../../hooks/useAdminCrud';
import { ragApi } from '../../lib/api';
import { useAdminTenantStore } from '../../store/tenantStore';
import { KnowledgeFormModal } from './components/KnowledgeFormModal';
import { RagPlayground } from './components/RagPlayground';
import type { KnowledgeChunkRecord } from './types';

export * from './types';

export function RagStudioPage() {
  const { selectedTenantId } = useAdminTenantStore();

  const fetchChunks = useCallback(async ({ tenantId }: { tenantId: string }) => {
    try {
      const res = await ragApi.list(tenantId === 'all' ? undefined : tenantId);
      if (res.success && Array.isArray(res.data)) {
        const records: KnowledgeChunkRecord[] = res.data.map((d: any) => ({
          id: d.id,
          businessId: d.businessId || tenantId || 'ecommerce',
          docTitle: d.docTitle || d.title || d.metadata?.title || d.sourceUrl || '知识切片',
          category: d.category || d.metadata?.category || '通用政策',
          content: d.content || d.chunkText || '',
          tokenCount: d.tokenCount || Math.ceil((d.content || d.chunkText || '').length * 1.3),
          updatedAt: d.updatedAt || (d.createdAt ? d.createdAt.split('T')[0] : '2026-02-23'),
        }));
        return records;
      }
    } catch (err) {
      console.warn('Failed to fetch remote chunks:', err);
    }
    return [];
  }, []);

  const createDocApi = useCallback(async (item: Partial<KnowledgeChunkRecord>, tenantId: string) => {
    const res = await ragApi.createDoc(
      {
        title: item.docTitle || '新知识切片',
        category: item.category || '通用政策',
        content: item.content || '',
        tenantId: item.businessId || tenantId,
      },
      tenantId,
    );
    return res.data || item;
  }, []);

  const deleteDocApi = useCallback(async (id: string, tenantId: string) => {
    await ragApi.deleteDoc(id, tenantId);
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
  } = useAdminCrud<KnowledgeChunkRecord>({
    fetchList: fetchChunks,
    createApi: createDocApi,
    deleteApi: deleteDocApi,
    tenantKey: 'businessId' as keyof KnowledgeChunkRecord,
    filterFn: (item, query, category, tenantId) => {
      if (tenantId !== 'all' && item.businessId !== tenantId) return false;
      if (category && item.category !== category) return false;
      if (query.trim()) {
        const q = query.toLowerCase();
        return (
          item.docTitle.toLowerCase().includes(q) ||
          item.content.toLowerCase().includes(q) ||
          item.category.toLowerCase().includes(q)
        );
      }
      return true;
    },
  });

  const [playQuery, setPlayQuery] = useState('');
  const [playResults, setPlayResults] = useState<Array<{ id: string; title: string; score: number; content: string }>>(
    [],
  );
  const [isSearching, setIsSearching] = useState(false);

  const [formData, setFormData] = useState<Partial<KnowledgeChunkRecord>>({});

  const handleOpenCreate = () => {
    setFormData({
      id: `chunk_${Date.now()}`,
      businessId: selectedTenantId === 'all' ? 'nike' : selectedTenantId,
      docTitle: '',
      category: '售后政策',
      content: '',
      tokenCount: 0,
    });
    setIsCreateOpen(true);
  };

  const handleOpenEdit = (chunk: KnowledgeChunkRecord) => {
    setFormData({ ...chunk });
    setIsEditOpen(true);
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (isCreateOpen) {
      if (!formData.docTitle || !formData.content) return;
      createItem({
        ...(formData as KnowledgeChunkRecord),
        tokenCount: Math.ceil((formData.content?.length || 0) * 1.3),
        updatedAt: new Date().toISOString().split('T')[0],
      });
    } else if (isEditOpen && formData.id) {
      updateItem('id', {
        ...(formData as KnowledgeChunkRecord),
        tokenCount: Math.ceil((formData.content?.length || 0) * 1.3),
        updatedAt: new Date().toISOString().split('T')[0],
      });
    }
  };

  const handleRunSearch = async () => {
    if (!playQuery.trim()) return;
    setIsSearching(true);
    try {
      const res = await ragApi.search(playQuery, selectedTenantId === 'all' ? 'ecommerce' : selectedTenantId);
      if (res.success && Array.isArray(res.data) && res.data.length > 0) {
        setPlayResults(res.data);
        setIsSearching(false);
        return;
      }
    } catch (err) {
      console.warn('RAG search API failed:', err);
    }

    setPlayResults([]);
    setIsSearching(false);
  };

  const columns = [
    {
      key: 'docTitle',
      header: '文档标题 / 所属商户',
      render: (row: KnowledgeChunkRecord) => (
        <div>
          <div className="font-semibold text-slate-900 text-xs">{row.docTitle}</div>
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
      key: 'category',
      header: '知识分类',
      render: (row: KnowledgeChunkRecord) => (
        <span className="text-xs bg-slate-100 text-slate-700 px-2 py-0.5 rounded font-medium">{row.category}</span>
      ),
    },
    {
      key: 'content',
      header: '知识切片文本 (Chunk Preview)',
      render: (row: KnowledgeChunkRecord) => (
        <div className="text-xs text-slate-600 truncate max-w-md">{row.content}</div>
      ),
    },
    {
      key: 'tokenCount',
      header: 'Tokens',
      render: (row: KnowledgeChunkRecord) => <span className="text-xs font-mono text-slate-500">{row.tokenCount}</span>,
    },
    {
      key: 'updatedAt',
      header: '更新时间',
      render: (row: KnowledgeChunkRecord) => <span className="text-xs text-slate-400 font-mono">{row.updatedAt}</span>,
    },
    {
      key: 'actions',
      header: '操作',
      align: 'right' as const,
      render: (row: KnowledgeChunkRecord) => (
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
    <div className="space-y-6">
      {/* 演练台 */}
      <RagPlayground
        selectedTenantId={selectedTenantId}
        query={playQuery}
        onQueryChange={setPlayQuery}
        onSearch={handleRunSearch}
        isSearching={isSearching}
        results={playResults}
      />

      {/* 知识切片列表 */}
      <div className="space-y-4">
        <FilterBar
          searchQuery={searchQuery}
          onSearchChange={setSearchQuery}
          searchPlaceholder="搜索切片标题、内容、分类..."
          statusFilter={statusFilter}
          onStatusChange={setStatusFilter}
          statusOptions={[
            { label: '售后政策', value: '售后政策' },
            { label: '商品知识', value: '商品知识' },
            { label: '会员权益', value: '会员权益' },
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
              新增知识切片
            </button>
          }
        />

        <DataTable<KnowledgeChunkRecord>
          columns={columns}
          data={paginatedData}
          emptyText="未检索到符合条件的知识库切片"
          pagination={{
            currentPage,
            pageSize,
            total,
            onPageChange: setCurrentPage,
          }}
        />
      </div>

      <KnowledgeFormModal
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
        title="确认删除该知识切片？"
        description={`删除切片 [${itemToDelete?.docTitle}] 后，向量检索将不再匹配该段知识内容。`}
        confirmText="确认删除"
      />
    </div>
  );
}
export default RagStudioPage;
