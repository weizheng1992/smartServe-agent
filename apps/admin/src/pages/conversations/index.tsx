import React from "react";
import { DataTable, FilterBar } from "../../components/crud";
import { useAdminCrud } from "../../hooks/useAdminCrud";
import { ThreadDeepTraceDrawer } from "./components/ThreadDeepTraceDrawer";
import type { ConversationRecord } from "./types";

export * from "./types";

const INITIAL_CONVERSATIONS: ConversationRecord[] = [
  {
    threadId: "t_nike_90214",
    userId: "u_vip_881",
    businessId: "nike",
    channel: "Web Widget",
    status: "waiting_approval",
    intent: "order_refund",
    messageCount: 8,
    totalTokens: 3420,
    costUsd: 0.0142,
    lastMessage: "申请对订单 ORD-2026-9901 进行退款 500 元（超额审核中）",
    updatedAt: "2026-02-23 16:45:10",
  },
  {
    threadId: "t_adi_40112",
    userId: "u_user_332",
    businessId: "adidas",
    channel: "Mobile App",
    status: "resolved",
    intent: "product_inquiry",
    messageCount: 5,
    totalTokens: 1890,
    costUsd: 0.0078,
    lastMessage: "Ultraboost Light 跑鞋尺码建议与库存查询已完成",
    updatedAt: "2026-02-23 15:30:22",
  },
  {
    threadId: "t_ecom_11094",
    userId: "u_buyer_554",
    businessId: "ecommerce",
    channel: "WeChat MiniApp",
    status: "active",
    intent: "order_status",
    messageCount: 3,
    totalTokens: 1100,
    costUsd: 0.0045,
    lastMessage: "包裹当前正在【上海转运中心】分拨发出",
    updatedAt: "2026-02-23 17:02:40",
  },
  {
    threadId: "t_nike_88710",
    userId: "u_runner_102",
    businessId: "nike",
    channel: "Web Widget",
    status: "resolved",
    intent: "faq_shipping",
    messageCount: 4,
    totalTokens: 1420,
    costUsd: 0.0059,
    lastMessage: "顺丰特快默认包邮，次日达服务说明",
    updatedAt: "2026-02-23 14:15:00",
  },
];

export function ConversationsPage() {
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
  } = useAdminCrud<ConversationRecord>({
    initialData: INITIAL_CONVERSATIONS,
    tenantKey: "businessId" as keyof ConversationRecord,
    filterFn: (item, query, status, tenantId) => {
      if (tenantId !== "all" && item.businessId !== tenantId) return false;
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
      key: "threadId",
      header: "会话 ID / 用户",
      render: (row: ConversationRecord) => (
        <div>
          <div className="font-semibold text-slate-900 font-mono text-xs">
            {row.threadId}
          </div>
          <div className="text-xs text-slate-400">User: {row.userId}</div>
        </div>
      ),
    },
    {
      key: "businessId",
      header: "归属商户 / 渠道",
      render: (row: ConversationRecord) => (
        <div>
          <span
            className={`inline-flex items-center px-2 py-0.5 rounded text-[11px] font-medium ${
              row.businessId === "nike"
                ? "bg-rose-50 text-rose-700"
                : row.businessId === "adidas"
                  ? "bg-blue-50 text-blue-700"
                  : "bg-amber-50 text-amber-700"
            }`}
          >
            {row.businessId.toUpperCase()}
          </span>
          <div className="text-xs text-slate-400 mt-0.5">{row.channel}</div>
        </div>
      ),
    },
    {
      key: "intent",
      header: "识别意图 / 最新摘要",
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
      key: "status",
      header: "会话状态",
      render: (row: ConversationRecord) => {
        const map = {
          active: {
            label: "进行中",
            cls: "bg-emerald-50 text-emerald-700 border-emerald-200",
          },
          waiting_approval: {
            label: "挂起待审批",
            cls: "bg-amber-50 text-amber-700 border-amber-200",
          },
          resolved: {
            label: "已完结",
            cls: "bg-slate-100 text-slate-600 border-slate-200",
          },
        };
        const st = map[row.status] || map.active;
        return (
          <span
            className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium border ${st.cls}`}
          >
            {st.label}
          </span>
        );
      },
    },
    {
      key: "costUsd",
      header: "Tokens / 成本",
      render: (row: ConversationRecord) => (
        <div>
          <div className="text-xs font-semibold text-slate-800">
            {row.totalTokens.toLocaleString()} tokens
          </div>
          <div className="text-[11px] text-slate-400 font-mono">
            ${row.costUsd.toFixed(4)}
          </div>
        </div>
      ),
    },
    {
      key: "updatedAt",
      header: "更新时间",
      render: (row: ConversationRecord) => (
        <span className="text-xs text-slate-400 font-mono">
          {row.updatedAt}
        </span>
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
          { label: "进行中 (Active)", value: "active" },
          { label: "待审批 (Waiting Approval)", value: "waiting_approval" },
          { label: "已完结 (Resolved)", value: "resolved" },
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
      />
    </div>
  );
}
export default ConversationsPage;
