import {
  ApprovalRiskBadge,
  Badge,
  Button,
  CheckCircle2,
  Input,
  ShieldAlert,
  diagnoseApprovalTrigger,
  getApprovalCategory,
  getApprovalContextData,
} from "ui";
import { useWorkbench } from "../workbench";

/** Tab 2: 待办审核中心 (HITL) —— AI 拦截的高危操作人工核决队列。 */
export function ApprovalsTab() {
  const {
    activeTab, setActiveTab,
    approvals, approvalStatusFilter, setApprovalStatusFilter, approvalActionFilter, setApprovalActionFilter, approvalSearchQuery, setApprovalSearchQuery,
    submittingActionId, setRejectionReasons,
    fetchDashboardData, handleApprovalAction,
    setInspectingApproval, setRejectingApprovalId, setRejectReasonInput,
    setActiveThreadId,
  } = useWorkbench();

  if (activeTab !== 'approvals') return null;

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

  const waitingCount = approvals.filter((a) => a.status === 'waiting').length;

  const FILTERS: Array<{ key: string; label: string; badge?: number }> = [
    { key: 'waiting', label: '⏳ 待审核', badge: waitingCount },
    { key: 'approved', label: '✅ 已核准' },
    { key: 'rejected', label: '❌ 已驳回' },
    { key: 'all', label: '全部记录' },
  ];

  return (
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
              {FILTERS.map((f) => (
                <button
                  key={f.key}
                  type="button"
                  onClick={() => setApprovalStatusFilter(f.key)}
                  className={`px-3 py-1 rounded-md transition cursor-pointer flex items-center gap-1.5 ${
                    approvalStatusFilter === f.key
                      ? 'bg-white text-slate-900 shadow-xs font-bold'
                      : 'text-slate-600 hover:text-slate-900'
                  }`}
                >
                  <span>{f.label}</span>
                  {f.badge ? (
                    <span className="bg-amber-500 text-white text-[10px] px-1.5 py-0.2 rounded-full font-bold">
                      {f.badge}
                    </span>
                  ) : null}
                </button>
              ))}
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
        {filteredList.length === 0 ? (
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
        ) : (
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
                {filteredList.map((approval) => (
                  <ApprovalRow key={approval.id} approval={approval} />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

/** 单行渲染:状态徽标与业务参数按 category 分派(模块级组件,避免
 *  定义在父组件体内导致每次键入搜索词整表重挂载)。 */
function ApprovalRow({ approval }: { approval: any }) {
  const {
    submittingActionId,
    handleApprovalAction,
    setInspectingApproval, setRejectingApprovalId, setRejectReasonInput,
    setActiveThreadId, setActiveTab,
  } = useWorkbench();
  const diag = diagnoseApprovalTrigger(approval);
  const isWaiting = approval.status === 'waiting';
  const isSubmitting = submittingActionId === approval.id;

  return (
    <tr className="hover:bg-slate-50/80 transition">
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

      <td className="p-3.5"><ApprovalParams approval={approval} /></td>

      <td className="p-3.5">
        <div className="font-medium text-slate-900">{approval.userId || '顾客'}</div>
        <div
          className="text-[10px] text-slate-400 font-mono truncate max-w-[130px]"
          title={approval.threadId}
        >
          {approval.threadId}
        </div>
      </td>

      <td className="p-3.5"><ApprovalStatusBadge status={approval.status} reason={approval.reason} /></td>

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
}

/** 业务核心参数列:refund / address / human / generic 四类分派。 */
function ApprovalParams({ approval }: { approval: any }) {
  const ctx = getApprovalContextData(approval);
  if (ctx.category === 'refund') {
    return (
      <div className="space-y-0.5">
        <div className="font-bold text-rose-600">
          ¥{ctx.refundAmount ? Number(ctx.refundAmount).toFixed(2) : '0.00'}
        </div>
        <div className="text-[11px] text-slate-500 font-mono">
          单号: {ctx.orderId || '未提供'}
        </div>
      </div>
    );
  }
  if (ctx.category === 'address') {
    return (
      <div className="space-y-0.5 max-w-xs">
        <div className="font-medium text-slate-900 truncate" title={ctx.newAddress || ''}>
          新: {ctx.newAddress || '未填写'}
        </div>
        <div className="text-[11px] text-slate-500">
          收件人: {ctx.recipientName || '顾客'} ({ctx.phone || '-'})
        </div>
      </div>
    );
  }
  if (ctx.category === 'human') {
    return (
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
    );
  }
  return <div className="text-[11px] text-slate-600 font-mono">{approval.actionType}</div>;
}

const STATUS_BADGES: Record<string, { text: string; cls: string; pulse?: boolean }> = {
  waiting: { text: '待审核', cls: 'bg-amber-100 text-amber-800 border-amber-300', pulse: true },
  approved: { text: '✅ 已核准', cls: 'bg-emerald-100 text-emerald-800 border-emerald-300' },
  rejected: { text: '❌ 已驳回', cls: 'bg-rose-100 text-rose-800 border-rose-300' },
  resolved_by_human: { text: '👨‍💼 人工已结', cls: 'bg-purple-100 text-purple-800 border-purple-300' },
  expired: { text: '⚠️ 已超时', cls: 'bg-slate-100 text-slate-600 border-slate-300' },
};

/** 状态列徽标(未知状态诚实原样展示)。 */
function ApprovalStatusBadge({ status, reason }: { status: string; reason?: string }) {
  const badge = STATUS_BADGES[status];
  if (!badge) {
    return (
      <Badge variant="outline" className="bg-slate-100 text-slate-700 border-slate-200 font-bold w-fit">
        {status}
      </Badge>
    );
  }
  return (
    <Badge
      variant="outline"
      className={`${badge.cls} font-bold w-fit ${badge.pulse ? 'flex items-center gap-1' : ''}`}
      title={status === 'rejected' ? (reason || '') : undefined}
    >
      {badge.pulse && <span className="w-1.5 h-1.5 rounded-full bg-amber-500 animate-pulse" />}
      {badge.text}
    </Badge>
  );
}
