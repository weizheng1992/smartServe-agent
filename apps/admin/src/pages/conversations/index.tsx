import React, { useCallback } from 'react';
import { DataTable, FilterBar } from '../../components/crud';
import { useAdminCrud } from '../../hooks/useAdminCrud';
import { conversationsApi } from '../../lib/api';
import { ThreadDeepTraceDrawer } from './components/ThreadDeepTraceDrawer';
import type { ConversationRecord } from './types';

export * from './types';

export function ConversationsPage() {
  const fetchConversations = useCallback(
    async ({
      tenantId,
      page,
      pageSize,
      query,
      status,
    }: {
      tenantId: string;
      page: number;
      pageSize: number;
      query?: string;
      status?: string;
    }) => {
      const res = await conversationsApi.list({
        tenantId,
        status: status || undefined,
        search: query || undefined,
        limit: pageSize,
        offset: (page - 1) * pageSize,
      });

      if (res.success && Array.isArray(res.conversations)) {
        const records: ConversationRecord[] = res.conversations.map((item: any) => ({
          threadId: item.threadId,
          userId: item.userId || 'anonymous_user',
          businessId: item.businessId || tenantId || 'ecommerce',
          channel: (item.metadata?.channel as string) || 'Web Widget',
          status: item.status as any,
          intent: (item.tags?.[0] as string) || (item.metadata?.intent as string) || 'general_inquiry',
          messageCount: item.metadata?.messageCount || 1,
          totalTokens: item.metadata?.totalTokens || 850,
          costUsd: item.metadata?.costUsd || 0.0035,
          lastMessage: item.lastMessageSnippet || '最新用户消息',
          updatedAt: item.updatedAt
            ? new Date(item.updatedAt).toLocaleString('zh-CN')
            : new Date().toLocaleString('zh-CN'),
        }));
        return { data: records, total: res.total ?? records.length };
      }

      return { data: [], total: 0 };
    },
    [],
  );

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
    isLoading,
    refetch,
    isDrawerOpen,
    selectedItem,
    openDrawer,
    closeDrawer,
  } = useAdminCrud<ConversationRecord>({
    fetchList: fetchConversations,
    tenantKey: 'businessId' as keyof ConversationRecord,
    filterFn: (item, query, status, tenantId) => {
      if (tenantId !== 'all' && item.businessId !== tenantId) return false;
      if (status && item.status !== status) return false;
      if (query.trim()) {
        const q = query.toLowerCase();
        return (
          item.threadId.toLowerCase().includes(q) ||
          item.userId.toLowerCase().includes(q) ||
          item.lastMessage.toLowerCase().includes(q) ||
          item.intent.toLowerCase().includes(q)
        );
      }
      return true;
    },
  });

  const columns = [
    {
      key: 'threadId',
      header: '会话 ID / 用户',
      render: (row: ConversationRecord) => (
        <div>
          <div className="font-semibold text-slate-900 font-mono text-xs">{row.threadId}</div>
          <div className="text-xs text-slate-400">User: {row.userId}</div>
        </div>
      ),
    },
    {
      key: 'businessId',
      header: '归属商户 / 渠道',
      render: (row: ConversationRecord) => (
        <div>
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
          <div className="text-xs text-slate-400 mt-0.5">{row.channel}</div>
        </div>
      ),
    },
    {
      key: 'intent',
      header: '识别意图 / 最新摘要',
      render: (row: ConversationRecord) => (
        <div className="max-w-md">
          <span className="text-[11px] font-mono px-1.5 py-0.5 bg-slate-100 text-slate-700 rounded mr-1.5">
            {row.intent}
          </span>
          <span className="text-xs text-slate-600 truncate inline-block align-bottom max-w-[260px]">
            {row.lastMessage}
          </span>
        </div>
      ),
    },
    {
      key: 'status',
      header: '会话状态',
      render: (row: ConversationRecord) => {
        const map = {
          active: {
            label: '进行中',
            cls: 'bg-emerald-50 text-emerald-700 border-emerald-200',
          },
          waiting_approval: {
            label: '挂起待审批',
            cls: 'bg-amber-50 text-amber-700 border-amber-200',
          },
          resolved: {
            label: '已完结',
            cls: 'bg-slate-100 text-slate-600 border-slate-200',
          },
        };
        const st = map[row.status] || map.active;
        return (
          <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium border ${st.cls}`}>
            {st.label}
          </span>
        );
      },
    },
    {
      key: 'costUsd',
      header: 'Tokens / 成本',
      render: (row: ConversationRecord) => (
        <div>
          <div className="text-xs font-semibold text-slate-800">{row.totalTokens.toLocaleString()} tokens</div>
          <div className="text-[11px] text-slate-400 font-mono">${row.costUsd.toFixed(4)}</div>
        </div>
      ),
    },
    {
      key: 'updatedAt',
      header: '更新时间',
      render: (row: ConversationRecord) => <span className="text-xs text-slate-400 font-mono">{row.updatedAt}</span>,
    },
    {
      key: 'actions',
      header: '操作',
      align: 'right' as const,
      render: (row: ConversationRecord) => (
        <div className="flex items-center justify-end gap-2">
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              openDrawer(row);
            }}
            className="text-xs text-blue-600 hover:text-blue-800 font-medium px-2.5 py-1 rounded-md hover:bg-blue-50 transition-colors cursor-pointer border border-blue-200"
          >
            查看详情
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
        searchPlaceholder="搜索会话ID、用户ID、意图、消息文本..."
        statusFilter={statusFilter}
        onStatusChange={setStatusFilter}
        statusOptions={[
          { label: '进行中 (Active)', value: 'active' },
          { label: '待审批 (Waiting Approval)', value: 'waiting_approval' },
          { label: '已完结 (Resolved)', value: 'resolved' },
        ]}
        showTenantFilter={true}
        onReset={handleResetFilters}
      />

      <DataTable<ConversationRecord>
        columns={columns}
        data={paginatedData}
        emptyText="未检索到符合条件的会话记录"
        onRowClick={openDrawer}
        rowKey={(row) => row.threadId}
        pagination={{
          currentPage,
          pageSize,
          total,
          onPageChange: setCurrentPage,
        }}
      />

      <ThreadDeepTraceDrawer
        isOpen={isDrawerOpen}
        onClose={closeDrawer}
        conversation={selectedItem}
        onUpdated={refetch}
      />
    </div>
  );
}
export default ConversationsPage;
