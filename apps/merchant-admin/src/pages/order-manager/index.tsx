import React from "react";
import {
  ApprovalContextDrawer,
  ApprovalRiskBadge,
  Badge,
  Button,
  CheckCircle2,
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Input,
  RichCardRenderer,
  ShieldAlert,
  Textarea,
  diagnoseApprovalTrigger,
  getApprovalCategory,
  getApprovalContextData,
} from "ui";
import { useWorkbench, useWorkbenchState, WorkbenchProvider, type Workbench } from "./workbench";
import { OrdersTab } from './components/orders-tab';
import { LiveDeskTab } from './components/live-desk-tab';
import { SpusTab } from './components/spus-tab';
import { SkusTab } from './components/skus-tab';
import { SpiLogsTab } from './components/spi-logs-tab';

import { useState } from "react";

export default function OrderWorkbench({ initialTab = "orders" }: { initialTab?: string }) {
  const w = useWorkbenchState(initialTab);
  return (
    <WorkbenchProvider value={w}>
      <WorkbenchShell />
    </WorkbenchProvider>
  );
}

function WorkbenchShell() {
  const w = useWorkbench();
  const {
    activeTab, setActiveTab,
    orders, auditLogs, spus, skus, approvals, conversations,
    activeThreadId, setActiveThreadId, activeThreadMessages, setActiveThreadMessages,
    loadConversationMessages,
    loading,
    orderStatusFilter, setOrderStatusFilter, orderSearchQuery, setOrderSearchQuery,
    approvalStatusFilter, setApprovalStatusFilter, approvalActionFilter, setApprovalActionFilter, approvalSearchQuery, setApprovalSearchQuery,
    liveDeskStatusFilter, setLiveDeskStatusFilter, liveDeskSearchQuery, setLiveDeskSearchQuery,
    spuCategoryFilter, setSpuCategoryFilter, spuSearchQuery, setSpuSearchQuery,
    skuStockFilter, setSkuStockFilter, skuSearchQuery, setSkuSearchQuery,
    spiActionFilter, setSpiActionFilter, spiSearchQuery, setSpiSearchQuery,
    shippingOrderId, setShippingOrderId, trackingNumberInput, setTrackingNumberInput,
    carrierInput, setCarrierInput, selectedLog, setSelectedLog, copiedLog, setCopiedLog,
    inspectingApproval, setInspectingApproval, isTakingOver,
    rejectingApprovalId, setRejectingApprovalId, rejectReasonInput, setRejectReasonInput,
    messagesEndRef,
    selectedOrderIds, setSelectedOrderIds, toggleOrderSelection,
    submittingActionId, setRejectionReasons,
    fetchDashboardData,
    handleApprovalAction, handleHumanReply, handleTakeover, handleSendMessage, handleShipOrder,
    inputMessage, setInputMessage,
    pendingApprovalsCount, paidOrdersCount, shippedOrdersCount, refundedOrdersCount, lowStockCount,
    filteredOrders, filteredConversations, spuCategories, filteredSpus, filteredSkus, filteredAuditLogs,
  } = w;
  return (
    <div className="min-h-screen bg-slate-100 flex flex-col font-sans">
      {/* 顶部商户后台 Header */}
      <header className="bg-slate-900 text-white border-b border-slate-800 h-16 flex items-center justify-between px-6 sticky top-0 z-20">
        <div className="flex items-center space-x-3">
          <div className="w-8 h-8 rounded bg-emerald-600 flex items-center justify-center font-bold text-white shadow-xs">
            A
          </div>
          <div>
            <div className="font-bold text-base tracking-tight flex items-center space-x-2">
              <span>极光潮品商户后台管理系统</span>
              <span className="text-[10px] bg-emerald-950 text-emerald-300 border border-emerald-800 px-2 py-0.5 rounded font-mono">
                Aurora Merchant Port 3005
              </span>
            </div>
            <div className="text-[11px] text-slate-400">
              独立物理隔离 · SPU/SKU 多规格电商 · HITL 审批中枢 · LiveDesk 在线客服
            </div>
          </div>
        </div>

        <div className="flex items-center space-x-4 text-xs">
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={fetchDashboardData}
            className="bg-slate-800 hover:bg-slate-700 text-slate-200 border-slate-700 h-8 cursor-pointer"
          >
            <span>🔄 刷新数据</span>
          </Button>
          <a
            href="/"
            className="px-3 py-1.5 bg-emerald-600 hover:bg-emerald-500 text-white font-medium rounded transition flex items-center space-x-1 shadow-xs cursor-pointer"
          >
            <span>🛍️ 返回商城前台</span>
          </a>
        </div>
      </header>

      {/* 主体工作台 */}
      <div className="max-w-7xl w-full mx-auto p-6 flex-1 flex flex-col space-y-6">
        {/* 顶部四栏核心指标看板 */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          {/* biome-ignore lint/a11y/useKeyWithClickEvents: 看板卡片点击为快捷导航,键盘路径由顶部 Tab 承担 */}
          <div
            onClick={() => setActiveTab('orders')}
            className="bg-white p-5 rounded-xl border border-slate-200 shadow-2xs flex items-center justify-between cursor-pointer hover:border-emerald-400 transition"
          >
            <div>
              <div className="text-xs text-slate-500 font-medium">累计订单总数</div>
              <div className="text-2xl font-bold text-slate-900 mt-1">{orders.length} 笔</div>
              <div className="text-[11px] text-slate-400 mt-1 flex gap-2">
                <span>待发: {paidOrdersCount}</span>
                <span>已发: {shippedOrdersCount}</span>
              </div>
            </div>
            <div className="text-3xl text-slate-300">📋</div>
          </div>
          {/* biome-ignore lint/a11y/useKeyWithClickEvents: 看板卡片点击为快捷导航,键盘路径由顶部 Tab 承担 */}
          <div
            onClick={() => setActiveTab('approvals')}
            className="bg-white p-5 rounded-xl border border-slate-200 shadow-2xs flex items-center justify-between cursor-pointer hover:border-amber-400 transition"
          >
            <div>
              <div className="text-xs text-slate-500 font-medium flex items-center space-x-1">
                <span>待人工审核工单</span>
                {pendingApprovalsCount > 0 && <span className="w-2 h-2 rounded-full bg-amber-500 animate-pulse" />}
              </div>
              <div
                className={`text-2xl font-bold mt-1 ${pendingApprovalsCount > 0 ? 'text-amber-600' : 'text-slate-900'}`}
              >
                {pendingApprovalsCount} 笔
              </div>
              <div className="text-[11px] text-amber-600/80 mt-1">
                {pendingApprovalsCount > 0 ? '需及时核决以放行流程' : '大盘运转平稳'}
              </div>
            </div>
            <div className="text-3xl text-amber-300">🛡️</div>
          </div>
          {/* biome-ignore lint/a11y/useKeyWithClickEvents: 看板卡片点击为快捷导航,键盘路径由顶部 Tab 承担 */}
          <div
            onClick={() => setActiveTab('live_desk')}
            className="bg-white p-5 rounded-xl border border-slate-200 shadow-2xs flex items-center justify-between cursor-pointer hover:border-blue-400 transition"
          >
            <div>
              <div className="text-xs text-slate-500 font-medium">活跃在线会话</div>
              <div className="text-2xl font-bold text-blue-600 mt-1">{conversations.length} 组</div>
              <div className="text-[11px] text-blue-500/80 mt-1">
                接管: {conversations.filter((c) => c.status === 'human_takeover').length} · 托管:{' '}
                {conversations.filter((c) => c.status !== 'human_takeover').length}
              </div>
            </div>
            <div className="text-3xl text-blue-300">💬</div>
          </div>
          {/* biome-ignore lint/a11y/useKeyWithClickEvents: 看板卡片点击为快捷导航,键盘路径由顶部 Tab 承担 */}
          <div
            onClick={() => setActiveTab('skus')}
            className="bg-white p-5 rounded-xl border border-slate-200 shadow-2xs flex items-center justify-between cursor-pointer hover:border-purple-400 transition"
          >
            <div>
              <div className="text-xs text-slate-500 font-medium flex items-center gap-1">
                <span>SKU 库存监控</span>
                {lowStockCount > 0 && (
                  <span className="text-[10px] bg-rose-100 text-rose-700 px-1.5 py-0.2 rounded font-bold">
                    {lowStockCount} 低库存
                  </span>
                )}
              </div>
              <div className="text-2xl font-bold text-slate-900 mt-1">{skus.length} 款</div>
              <div className="text-[11px] text-slate-400 mt-1">SPU 库: {spus.length} 款商品</div>
            </div>
            <div className="text-3xl text-purple-300">📦</div>
          </div>
        </div>

        {/* 标签栏导航 */}
        <div className="flex border-b border-slate-200 bg-white rounded-t-xl px-4 pt-3 gap-6 shadow-2xs overflow-x-auto">
          <button
            type="button"
            onClick={() => setActiveTab('orders')}
            className={`pb-3 text-sm font-semibold flex items-center space-x-2 border-b-2 transition whitespace-nowrap cursor-pointer ${
              activeTab === 'orders'
                ? 'border-emerald-600 text-emerald-700'
                : 'border-transparent text-slate-600 hover:text-slate-900'
            }`}
          >
            <span>📋 订单中心</span>
            <span className="bg-slate-100 text-slate-600 text-xs px-2 py-0.5 rounded-full">{orders.length}</span>
          </button>

          <button
            type="button"
            onClick={() => setActiveTab('approvals')}
            className={`pb-3 text-sm font-semibold flex items-center space-x-2 border-b-2 transition whitespace-nowrap cursor-pointer ${
              activeTab === 'approvals'
                ? 'border-amber-500 text-amber-700'
                : 'border-transparent text-slate-600 hover:text-slate-900'
            }`}
          >
            <span>🛡️ 待办审核 (HITL)</span>
            <span
              className={`text-xs px-2 py-0.5 rounded-full font-bold ${
                pendingApprovalsCount > 0 ? 'bg-amber-100 text-amber-800 animate-pulse' : 'bg-slate-100 text-slate-600'
              }`}
            >
              {pendingApprovalsCount}
            </span>
          </button>

          <button
            type="button"
            onClick={() => setActiveTab('live_desk')}
            className={`pb-3 text-sm font-semibold flex items-center space-x-2 border-b-2 transition whitespace-nowrap cursor-pointer ${
              activeTab === 'live_desk'
                ? 'border-blue-600 text-blue-700'
                : 'border-transparent text-slate-600 hover:text-slate-900'
            }`}
          >
            <span>💬 在线客服工作台</span>
            <span className="bg-blue-100 text-blue-700 text-xs px-2 py-0.5 rounded-full font-bold">
              {conversations.length}
            </span>
          </button>

          <button
            type="button"
            onClick={() => setActiveTab('spus')}
            className={`pb-3 text-sm font-semibold flex items-center space-x-2 border-b-2 transition whitespace-nowrap cursor-pointer ${
              activeTab === 'spus'
                ? 'border-emerald-600 text-emerald-700'
                : 'border-transparent text-slate-600 hover:text-slate-900'
            }`}
          >
            <span>🏷️ SPU 商品库</span>
            <span className="bg-slate-100 text-slate-600 text-xs px-2 py-0.5 rounded-full">{spus.length}</span>
          </button>

          <button
            type="button"
            onClick={() => setActiveTab('skus')}
            className={`pb-3 text-sm font-semibold flex items-center space-x-2 border-b-2 transition whitespace-nowrap cursor-pointer ${
              activeTab === 'skus'
                ? 'border-emerald-600 text-emerald-700'
                : 'border-transparent text-slate-600 hover:text-slate-900'
            }`}
          >
            <span>📦 SKU 规格库存</span>
            <span className="bg-slate-100 text-slate-600 text-xs px-2 py-0.5 rounded-full">{skus.length}</span>
          </button>

          <button
            type="button"
            onClick={() => setActiveTab('spi_logs')}
            className={`pb-3 text-sm font-semibold flex items-center space-x-2 border-b-2 transition whitespace-nowrap cursor-pointer ${
              activeTab === 'spi_logs'
                ? 'border-emerald-600 text-emerald-700'
                : 'border-transparent text-slate-600 hover:text-slate-900'
            }`}
          >
            <span>🔌 SPI 开放审计流水</span>
            <span className="bg-emerald-100 text-emerald-700 text-xs px-2 py-0.5 rounded-full font-bold">
              {auditLogs.length}
            </span>
          </button>
        </div>

        {/* Tab 1: 订单中心 */}
        <OrdersTab />

        {/* Tab 2: 待办审核中心 (HITL) */}
        {activeTab === 'approvals' && (
          <div className="space-y-4">
            <div className="bg-amber-50 border border-amber-200 p-4 rounded-xl flex items-center justify-between">
              <div className="flex items-center space-x-3">
                <ShieldAlert className="w-6 h-6 text-amber-600 shrink-0" />
                <div>
                  <h4 className="text-sm font-bold text-amber-900">
                    商户待办安全审核中心 (Human-in-the-Loop Safe Approvals)
                  </h4>
                  <p className="text-xs text-amber-700 mt-0.5">
                    展示 AI
                    决策引擎拦截的高危操作（如大额退款、发货前改地址等）。商户审核决议后，系统将通过事务发件箱自动恢复工作流执行。
                  </p>
                </div>
              </div>
              <Button
                type="button"
                size="sm"
                onClick={fetchDashboardData}
                className="bg-amber-600 text-white text-xs font-semibold hover:bg-amber-700 shrink-0 h-8 cursor-pointer"
              >
                🔄 刷新工单
              </Button>
            </div>

            <div className="bg-white rounded-xl border border-slate-200 shadow-2xs overflow-hidden">
              {/* 工具栏: 状态筛选 Tab + 类型下拉 + 关键词搜索 */}
              <div className="p-3.5 border-b border-slate-100 bg-slate-50 flex flex-wrap items-center justify-between gap-3">
                <div className="flex items-center gap-2 flex-wrap">
                  <div className="flex bg-slate-200/80 p-0.5 rounded-lg text-xs font-semibold">
                    <button
                      type="button"
                      onClick={() => setApprovalStatusFilter('waiting')}
                      className={`px-3 py-1 rounded-md transition cursor-pointer flex items-center gap-1.5 ${
                        approvalStatusFilter === 'waiting'
                          ? 'bg-white text-slate-900 shadow-xs font-bold'
                          : 'text-slate-600 hover:text-slate-900'
                      }`}
                    >
                      <span>⏳ 待审核</span>
                      {approvals.filter((a) => a.status === 'waiting').length > 0 && (
                        <span className="bg-amber-500 text-white text-[10px] px-1.5 py-0.2 rounded-full font-bold">
                          {approvals.filter((a) => a.status === 'waiting').length}
                        </span>
                      )}
                    </button>
                    <button
                      type="button"
                      onClick={() => setApprovalStatusFilter('approved')}
                      className={`px-3 py-1 rounded-md transition cursor-pointer ${
                        approvalStatusFilter === 'approved'
                          ? 'bg-white text-slate-900 shadow-xs font-bold'
                          : 'text-slate-600 hover:text-slate-900'
                      }`}
                    >
                      ✅ 已核准
                    </button>
                    <button
                      type="button"
                      onClick={() => setApprovalStatusFilter('rejected')}
                      className={`px-3 py-1 rounded-md transition cursor-pointer ${
                        approvalStatusFilter === 'rejected'
                          ? 'bg-white text-slate-900 shadow-xs font-bold'
                          : 'text-slate-600 hover:text-slate-900'
                      }`}
                    >
                      ❌ 已驳回
                    </button>
                    <button
                      type="button"
                      onClick={() => setApprovalStatusFilter('all')}
                      className={`px-3 py-1 rounded-md transition cursor-pointer ${
                        approvalStatusFilter === 'all'
                          ? 'bg-white text-slate-900 shadow-xs font-bold'
                          : 'text-slate-600 hover:text-slate-900'
                      }`}
                    >
                      全部记录
                    </button>
                  </div>

                  <select
                    value={approvalActionFilter}
                    onChange={(e) => setApprovalActionFilter(e.target.value)}
                    aria-label="筛选业务操作类型"
                    className="px-2.5 py-1 text-xs border border-slate-200 rounded-lg bg-white text-slate-700 font-medium focus:outline-hidden focus:ring-1 focus:ring-blue-500"
                  >
                    <option value="all">全部业务类型</option>
                    <option value="refund">💰 退款审核 (processRefund)</option>
                    <option value="address">🚚 修改地址 (changeAddress)</option>
                    <option value="human">🎧 升级人工 (human_escalation)</option>
                  </select>
                </div>

                <div className="flex items-center gap-2">
                  <Input
                    type="text"
                    placeholder="搜索单号 / 会话 / 顾客 / 原因..."
                    value={approvalSearchQuery}
                    onChange={(e) => setApprovalSearchQuery(e.target.value)}
                    className="text-xs h-8 w-64 bg-white"
                  />
                </div>
              </div>

              {/* 表格内容与空状态 */}
              {(() => {
                const filteredList = approvals.filter((item) => {
                  if (approvalStatusFilter !== 'all' && item.status !== approvalStatusFilter) {
                    return false;
                  }
                  if (approvalActionFilter !== 'all') {
                    const cat = getApprovalCategory(item.actionType);
                    if (approvalActionFilter === 'refund' && cat !== 'refund') return false;
                    if (approvalActionFilter === 'address' && cat !== 'address') return false;
                    if (approvalActionFilter === 'human' && cat !== 'human') return false;
                  }
                  if (approvalSearchQuery.trim()) {
                    const q = approvalSearchQuery.toLowerCase().trim();
                    const ctx = getApprovalContextData(item as any);
                    const str =
                      `${item.id} ${item.threadId} ${item.userId || ''} ${item.userEmail || ''} ${ctx.orderId || ''} ${ctx.reason || ''} ${ctx.userInput || ''} ${item.actionType || ''}`.toLowerCase();
                    if (!str.includes(q)) return false;
                  }
                  return true;
                });

                if (filteredList.length === 0) {
                  return (
                    <div className="p-12 text-center space-y-3">
                      <CheckCircle2 className="w-10 h-10 text-emerald-500 mx-auto" />
                      <h4 className="text-sm font-bold text-slate-800">
                        {approvalStatusFilter === 'waiting'
                          ? '当前大盘一片绿灯，暂无待审核任务'
                          : '未找到符合筛选条件的审核记录'}
                      </h4>
                      <p className="text-xs text-slate-400">
                        {approvalStatusFilter === 'waiting'
                          ? '当顾客在前台商城触发超阈值退款或关键地址变更时将在此排队待办。'
                          : '建议调整状态标签或清空搜索关键字重新查询。'}
                      </p>
                    </div>
                  );
                }

                return (
                  <div className="overflow-x-auto">
                    <table className="w-full text-left text-xs">
                      <thead className="bg-slate-50 border-b border-slate-200 text-slate-500 uppercase font-semibold">
                        <tr>
                          <th className="p-3.5">工单信息</th>
                          <th className="p-3.5">触发动作 / 风控诊断</th>
                          <th className="p-3.5">业务核心参数</th>
                          <th className="p-3.5">关联顾客 / 会话</th>
                          <th className="p-3.5">状态</th>
                          <th className="p-3.5 text-right">操作</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-slate-100 text-slate-700">
                        {filteredList.map((approval) => {
                          const diag = diagnoseApprovalTrigger(approval as any);
                          const ctx = getApprovalContextData(approval as any);
                          const isWaiting = approval.status === 'waiting';
                          const isSubmitting = submittingActionId === approval.id;

                          return (
                            <tr key={approval.id} className="hover:bg-slate-50/80 transition">
                              <td className="p-3.5">
                                <div className="font-mono font-bold text-slate-900">{approval.id.slice(0, 8)}...</div>
                                <div className="text-[10px] text-slate-400 mt-0.5">
                                  {approval.createdAt
                                    ? new Date(approval.createdAt).toLocaleString('zh-CN', {
                                        month: '2-digit',
                                        day: '2-digit',
                                        hour: '2-digit',
                                        minute: '2-digit',
                                      })
                                    : '-'}
                                </div>
                              </td>

                              <td className="p-3.5">
                                <div className="flex items-center gap-1.5 mb-1">
                                  <ApprovalRiskBadge riskLevel={diag.riskLevel} />
                                  <span className="font-semibold text-slate-900">{diag.title.split(' (')[0]}</span>
                                </div>
                                <div className="text-[11px] text-slate-500 max-w-xs truncate" title={diag.triggerCause}>
                                  {diag.triggerCause}
                                </div>
                              </td>

                              <td className="p-3.5">
                                {ctx.category === 'refund' && (
                                  <div className="space-y-0.5">
                                    <div className="font-bold text-rose-600">
                                      ¥{ctx.refundAmount ? Number(ctx.refundAmount).toFixed(2) : '0.00'}
                                    </div>
                                    <div className="text-[11px] text-slate-500 font-mono">
                                      单号: {ctx.orderId || '未提供'}
                                    </div>
                                  </div>
                                )}
                                {ctx.category === 'address' && (
                                  <div className="space-y-0.5 max-w-xs">
                                    <div className="font-medium text-slate-900 truncate" title={ctx.newAddress || ''}>
                                      新: {ctx.newAddress || '未填写'}
                                    </div>
                                    <div className="text-[11px] text-slate-500">
                                      收件人: {ctx.recipientName || '顾客'} ({ctx.phone || '-'})
                                    </div>
                                  </div>
                                )}
                                {ctx.category === 'human' && (
                                  <div className="space-y-0.5 max-w-xs">
                                    <div
                                      className="font-medium text-slate-800 line-clamp-1"
                                      title={ctx.userInput || ctx.reason || ''}
                                    >
                                      诉求: {ctx.userInput || ctx.reason || '转接人工客服'}
                                    </div>
                                    <div className="text-[11px] text-amber-600">
                                      来源: {ctx.triggerSource || 'AI 对话智能升级'}
                                    </div>
                                  </div>
                                )}
                                {ctx.category === 'generic' && (
                                  <div className="text-[11px] text-slate-600 font-mono">{approval.actionType}</div>
                                )}
                              </td>

                              <td className="p-3.5">
                                <div className="font-medium text-slate-900">{approval.userId || '顾客'}</div>
                                <div
                                  className="text-[10px] text-slate-400 font-mono truncate max-w-[130px]"
                                  title={approval.threadId}
                                >
                                  {approval.threadId}
                                </div>
                              </td>

                              <td className="p-3.5">
                                {approval.status === 'waiting' && (
                                  <Badge
                                    variant="outline"
                                    className="bg-amber-100 text-amber-800 border-amber-300 font-bold flex items-center gap-1 w-fit"
                                  >
                                    <span className="w-1.5 h-1.5 rounded-full bg-amber-500 animate-pulse" />
                                    待审核
                                  </Badge>
                                )}
                                {approval.status === 'approved' && (
                                  <Badge
                                    variant="outline"
                                    className="bg-emerald-100 text-emerald-800 border-emerald-300 font-bold w-fit"
                                  >
                                    ✅ 已核准
                                  </Badge>
                                )}
                                {approval.status === 'rejected' && (
                                  <Badge
                                    variant="outline"
                                    className="bg-rose-100 text-rose-800 border-rose-300 font-bold w-fit"
                                    title={approval.reason || ''}
                                  >
                                    ❌ 已驳回
                                  </Badge>
                                )}
                                {approval.status === 'resolved_by_human' && (
                                  <Badge
                                    variant="outline"
                                    className="bg-purple-100 text-purple-800 border-purple-300 font-bold w-fit"
                                  >
                                    👨‍💼 人工已结
                                  </Badge>
                                )}
                                {approval.status === 'expired' && (
                                  <Badge
                                    variant="outline"
                                    className="bg-slate-100 text-slate-600 border-slate-300 font-bold w-fit"
                                  >
                                    ⚠️ 已超时
                                  </Badge>
                                )}
                                {!['waiting', 'approved', 'rejected', 'resolved_by_human', 'expired'].includes(
                                  approval.status,
                                ) && (
                                  <Badge
                                    variant="outline"
                                    className="bg-slate-100 text-slate-700 border-slate-200 w-fit"
                                  >
                                    {approval.status}
                                  </Badge>
                                )}
                              </td>

                              <td className="p-3.5 text-right">
                                <div className="flex items-center justify-end gap-1.5">
                                  {isWaiting && (
                                    <>
                                      <Button
                                        type="button"
                                        size="sm"
                                        disabled={isSubmitting}
                                        onClick={() => handleApprovalAction(approval.id, 'approve')}
                                        className="bg-emerald-600 hover:bg-emerald-500 text-white text-xs h-7 px-2.5 font-bold shadow-2xs cursor-pointer"
                                      >
                                        通过
                                      </Button>
                                      <Button
                                        type="button"
                                        size="sm"
                                        disabled={isSubmitting}
                                        onClick={() => {
                                          setRejectingApprovalId(approval.id);
                                          setRejectReasonInput('');
                                        }}
                                        className="bg-rose-600 hover:bg-rose-500 text-white text-xs h-7 px-2.5 font-bold shadow-2xs cursor-pointer"
                                      >
                                        驳回
                                      </Button>
                                    </>
                                  )}
                                  <Button
                                    type="button"
                                    variant="secondary"
                                    size="sm"
                                    onClick={() => setInspectingApproval(approval)}
                                    className="text-xs h-7 px-2.5 font-medium bg-slate-100 hover:bg-slate-200 text-slate-700 cursor-pointer"
                                  >
                                    详情
                                  </Button>
                                  <Button
                                    type="button"
                                    variant="outline"
                                    size="sm"
                                    onClick={() => {
                                      setActiveThreadId(approval.threadId);
                                      setActiveTab('live_desk');
                                    }}
                                    className="text-xs h-7 px-2 text-blue-600 hover:text-blue-700 hover:bg-blue-50 border-blue-200 font-medium cursor-pointer"
                                  >
                                    进会话
                                  </Button>
                                </div>
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                );
              })()}
            </div>
          </div>
        )}

        {/* Tab 3: 在线客服工作台 (Live Desk Takeover) */}
        <LiveDeskTab />

        {/* Tab 4: SPU 商品库 */}
        <SpusTab />

        {/* Tab 5: SKU 规格库存管理 */}
        <SkusTab />

        {/* Tab 6: AI 客服对接配置与 SPI 审计流水 */}
        <SpiLogsTab />
      </div>

      {/* 审核上下文抽屉 */}
      <ApprovalContextDrawer
        isOpen={Boolean(inspectingApproval)}
        onClose={() => setInspectingApproval(null)}
        approval={inspectingApproval as any}
        onApprove={async (id) => {
          await handleApprovalAction(id, 'approve');
        }}
        onReject={async (id, reason) => {
          if (reason) {
            setRejectionReasons((prev) => ({ ...prev, [id]: reason }));
          }
          await handleApprovalAction(id, 'reject');
        }}
        onHumanReply={async (id, replyMsg, isFinish) => {
          await handleHumanReply(id, replyMsg, isFinish);
        }}
      />

      {/* 发货弹窗 */}
      <Dialog open={Boolean(shippingOrderId)} onOpenChange={(open) => !open && setShippingOrderId(null)}>
        <DialogContent className="max-w-sm p-6 bg-white text-slate-900 border-slate-200">
          <DialogHeader className="pb-3 border-b border-slate-100">
            <DialogTitle className="text-base font-bold text-slate-900">订单一键发货</DialogTitle>
            <p className="text-xs text-slate-500 mt-1 font-mono">订单号: {shippingOrderId}</p>
          </DialogHeader>

          <div className="space-y-3 py-3">
            <div>
              <label htmlFor="ship-carrier" className="block text-xs font-semibold text-slate-700 mb-1">
                承运快递公司
              </label>
              <select
                id="ship-carrier"
                value={carrierInput}
                onChange={(e) => setCarrierInput(e.target.value)}
                className="w-full px-3 py-2 text-xs border border-slate-300 rounded-lg bg-white focus:outline-hidden focus:ring-2 focus:ring-emerald-500"
              >
                <option value="SF">顺丰速运 (SF Express)</option>
                <option value="JD">京东快递 (JD Logistics)</option>
                <option value="ZTO">中通快递 (ZTO)</option>
                <option value="EMS">邮政 EMS</option>
              </select>
            </div>

            <div>
              <label htmlFor="ship-tracking" className="block text-xs font-semibold text-slate-700 mb-1">
                快递运单号
              </label>
              <Input
                id="ship-tracking"
                type="text"
                value={trackingNumberInput}
                onChange={(e) => setTrackingNumberInput(e.target.value)}
                className="text-xs h-9 bg-white font-mono"
                placeholder="请输入运单号..."
              />
            </div>
          </div>

          <DialogFooter className="gap-2 sm:gap-0 pt-3 border-t border-slate-100">
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => setShippingOrderId(null)}
              className="text-xs cursor-pointer"
            >
              取消
            </Button>
            <Button
              type="button"
              size="sm"
              onClick={() => shippingOrderId && handleShipOrder(shippingOrderId)}
              className="bg-blue-600 hover:bg-blue-500 text-white text-xs font-bold cursor-pointer"
            >
              确认发货并锁定地址
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* 报文查看弹窗 */}
      <Dialog open={Boolean(selectedLog)} onOpenChange={(open) => !open && setSelectedLog(null)}>
        <DialogContent className="max-w-lg p-6 bg-white text-slate-900 border-slate-200">
          <DialogHeader className="pb-3 border-b border-slate-100">
            <DialogTitle className="text-sm font-bold text-slate-900 flex items-center justify-between">
              <span>SPI 调用结果 Payload</span>
              {selectedLog && (
                <span className="text-xs font-mono font-normal text-slate-500">
                  {selectedLog.action_type} · {selectedLog.order_id}
                </span>
              )}
            </DialogTitle>
          </DialogHeader>

          <div className="py-3">
            <pre className="bg-slate-900 text-emerald-400 p-3.5 rounded-xl text-xs overflow-x-auto max-h-72 font-mono leading-relaxed border border-slate-800">
              {JSON.stringify(selectedLog?.payload, null, 2)}
            </pre>
          </div>

          <DialogFooter className="pt-3 border-t border-slate-100 flex items-center justify-between">
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => {
                if (selectedLog?.payload) {
                  navigator.clipboard.writeText(JSON.stringify(selectedLog.payload, null, 2));
                  setCopiedLog(true);
                  setTimeout(() => setCopiedLog(false), 2000);
                }
              }}
              className="text-xs cursor-pointer"
            >
              {copiedLog ? '✓ 已复制 JSON' : '📋 复制 JSON'}
            </Button>
            <Button
              type="button"
              size="sm"
              onClick={() => setSelectedLog(null)}
              className="bg-slate-900 text-white text-xs font-semibold hover:bg-slate-800 cursor-pointer"
            >
              关闭
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* 驳回原因输入弹窗 */}
      <Dialog open={Boolean(rejectingApprovalId)} onOpenChange={(open) => !open && setRejectingApprovalId(null)}>
        <DialogContent className="max-w-md p-6 bg-white text-slate-900 border-slate-200">
          <DialogHeader className="pb-3 border-b border-slate-100">
            <DialogTitle className="text-base font-bold text-slate-900">驳回审批工单</DialogTitle>
            <p className="text-xs text-slate-500 mt-1 font-mono">工单 ID: {rejectingApprovalId}</p>
          </DialogHeader>

          <div className="space-y-3 py-3">
            <label htmlFor="reject-reason" className="block text-xs font-semibold text-slate-700">
              请输入驳回原因 (将通知顾客并载入会话工作流)
            </label>
            <Textarea
              id="reject-reason"
              value={rejectReasonInput}
              onChange={(e) => setRejectReasonInput(e.target.value)}
              rows={3}
              placeholder="例如：物流轨迹显示已由本人签收，不符合退款条件..."
              className="w-full text-xs p-2.5 border border-slate-300 rounded-lg focus:outline-hidden focus:ring-2 focus:ring-rose-500 bg-white"
            />
            <div className="flex flex-wrap gap-1.5 pt-1">
              <span className="text-[11px] text-slate-400">常用快捷模板:</span>
              {[
                '物流已签收，驳回退款诉求',
                '已超过售后服务有效退款窗口',
                '商品已拆封使用，不满足退货条件',
                '请提供清晰的商品破损照片后再试',
              ].map((tpl) => (
                <button
                  key={tpl}
                  type="button"
                  onClick={() => setRejectReasonInput(tpl)}
                  className="text-[11px] bg-slate-100 hover:bg-slate-200 text-slate-700 px-2 py-0.5 rounded cursor-pointer transition"
                >
                  {tpl}
                </button>
              ))}
            </div>
          </div>

          <DialogFooter className="gap-2 sm:gap-0 pt-3 border-t border-slate-100">
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => {
                setRejectingApprovalId(null);
                setRejectReasonInput('');
              }}
              className="text-xs cursor-pointer"
            >
              取消
            </Button>
            <Button
              type="button"
              size="sm"
              disabled={submittingActionId === rejectingApprovalId}
              onClick={async () => {
                if (!rejectingApprovalId) return;
                if (rejectReasonInput) {
                  setRejectionReasons((prev) => ({
                    ...prev,
                    [rejectingApprovalId]: rejectReasonInput,
                  }));
                }
                await handleApprovalAction(rejectingApprovalId, 'reject', rejectReasonInput);
                setRejectingApprovalId(null);
                setRejectReasonInput('');
              }}
              className="bg-rose-600 hover:bg-rose-500 text-white text-xs font-bold cursor-pointer"
            >
              确认驳回
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
