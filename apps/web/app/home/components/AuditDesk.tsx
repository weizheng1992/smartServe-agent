import type React from 'react';
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardFooter,
  CardHeader,
  CardTitle,
  CheckCircle2,
  ImageIcon,
  Input,
  Loader2,
  Shield,
  X,
  XCircle,
} from 'ui';
import type { UserSession } from '../hooks/types';

interface AuditDeskProps {
  currentUser: UserSession | null;
  allApprovals: any[];
  selectedApprovalId: string | null;
  setSelectedApprovalId: (id: string | null) => void;
  auditFilter: 'ALL' | 'WAITING' | 'APPROVED' | 'REJECTED' | 'EXPIRED';
  setAuditFilter: (filter: 'ALL' | 'WAITING' | 'APPROVED' | 'REJECTED' | 'EXPIRED') => void;
  rejectionInput: string;
  setRejectionReason: (val: string) => void;
  isSubmitting: boolean;
  handleApprovalAction: (approvalId: string, action: 'approve' | 'reject') => Promise<void>;
  setActiveTab: (tab: 'CHAT_DESK' | 'AUDIT_DESK') => void;
}

export function AuditDesk({
  currentUser,
  allApprovals,
  selectedApprovalId,
  setSelectedApprovalId,
  auditFilter,
  setAuditFilter,
  rejectionInput,
  setRejectionReason,
  isSubmitting,
  handleApprovalAction,
  setActiveTab,
}: AuditDeskProps) {
  return (
    <div className="flex-1 flex flex-col bg-slate-950 p-6 overflow-hidden">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 pb-6 border-b border-slate-800 shrink-0">
        <div className="space-y-1">
          <div className="flex items-center gap-2">
            <Shield className="h-5 w-5 text-indigo-400" />
            <h1 className="text-lg font-bold tracking-tight text-slate-100 uppercase">
              smartServe 客服安全审查与核签大盘
            </h1>
          </div>
          <p className="text-xs text-slate-500 font-medium">全渠道多租户 Human-in-the-Loop 安全拦截工单审计平台</p>
        </div>
        <div className="flex gap-1.5 bg-slate-900 p-1 rounded-xl border border-slate-800 self-start shrink-0">
          {(['ALL', 'WAITING', 'APPROVED', 'REJECTED', 'EXPIRED'] as const).map((filter) => {
            const count = allApprovals.filter((a) => filter === 'ALL' || a.status.toUpperCase() === filter).length;
            const labelMap = {
              ALL: '全部',
              WAITING: '待审批',
              APPROVED: '已核准',
              REJECTED: '已驳回',
              EXPIRED: '已超时',
            };
            const active = auditFilter === filter;

            return (
              <button
                key={filter}
                type="button"
                onClick={() => {
                  setAuditFilter(filter);
                  setSelectedApprovalId(null);
                }}
                className={`px-3 py-1.5 rounded-lg text-xs font-semibold tracking-wide transition flex items-center gap-1.5 ${
                  active
                    ? 'bg-indigo-600 text-white shadow-lg shadow-indigo-600/10'
                    : 'text-slate-400 hover:text-slate-200 bg-transparent'
                }`}
              >
                <span>{labelMap[filter]}</span>
                <span
                  className={`text-[10px] px-1 rounded-md ${active ? 'bg-indigo-700 text-white' : 'bg-slate-800 text-slate-500'}`}
                >
                  {count}
                </span>
              </button>
            );
          })}
        </div>
      </div>

      {/* Content Area */}
      <div className="flex-1 flex gap-6 overflow-hidden pt-6">
        {/* Left Column: Approvals List */}
        <div className="w-80 md:w-96 flex flex-col bg-slate-900/40 rounded-2xl border border-slate-900 overflow-y-auto shrink-0 p-3 space-y-2">
          <span className="text-[10px] font-bold text-slate-500 tracking-wider uppercase block px-2 mb-1">
            安全审核工单清单 (
            {allApprovals.filter((a) => auditFilter === 'ALL' || a.status.toUpperCase() === auditFilter).length})
          </span>
          {allApprovals.filter((a) => auditFilter === 'ALL' || a.status.toUpperCase() === auditFilter).length === 0 ? (
            <div className="py-20 text-center flex flex-col items-center justify-center gap-3">
              <CheckCircle2 className="h-8 w-8 text-slate-700 animate-pulse" />
              <span className="text-xs text-slate-500 font-medium">当前列表下没有任何审核工单</span>
            </div>
          ) : (
            allApprovals
              .filter((a) => auditFilter === 'ALL' || a.status.toUpperCase() === auditFilter)
              .map((item) => {
                const active = selectedApprovalId === item.id;
                const dateStr = new Date(item.createdAt).toLocaleString([], {
                  month: '2-digit',
                  day: '2-digit',
                  hour: '2-digit',
                  minute: '2-digit',
                });

                const badgeStyle =
                  {
                    waiting: 'bg-amber-500/10 text-amber-400 border-amber-500/20',
                    approved: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20',
                    rejected: 'bg-rose-500/10 text-rose-400 border-rose-500/20',
                    expired: 'bg-slate-800 text-slate-500 border-transparent',
                  }[item.status as 'waiting' | 'approved' | 'rejected' | 'expired'] ||
                  'bg-slate-800 text-slate-400 border-transparent';

                const statusTextMap = {
                  waiting: '待审批',
                  approved: '已核准',
                  rejected: '已驳回',
                  expired: '已超时',
                };

                return (
                  <button
                    key={item.id}
                    type="button"
                    onClick={() => setSelectedApprovalId(item.id)}
                    className={`w-full text-left p-3.5 rounded-xl border transition group ${
                      active
                        ? 'bg-indigo-600/10 border-indigo-500/30'
                        : 'bg-slate-900 border-slate-850/60 hover:bg-slate-850/40 hover:border-slate-800'
                    }`}
                  >
                    <div className="flex items-center justify-between gap-2 mb-2">
                      <span className="text-xs font-bold text-slate-200 truncate font-mono">
                        ID: {item.id.substring(0, 8)}...
                      </span>
                      <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded border ${badgeStyle}`}>
                        {statusTextMap[item.status as 'waiting' | 'approved' | 'rejected' | 'expired'] || item.status}
                      </span>
                    </div>
                    <div className="text-xs text-slate-300 font-semibold mb-1">
                      动作类别: <span className="text-indigo-400 font-bold">{item.actionType}</span>
                    </div>
                    <div className="flex items-center justify-between mt-2.5 pt-2 border-t border-slate-800/60 text-[10px] text-slate-500 font-mono">
                      <span>{dateStr}</span>
                      <span className="truncate max-w-[150px]">会话: {item.threadId.substring(0, 10)}...</span>
                    </div>
                  </button>
                );
              })
          )}
        </div>

        {/* Right Column: Selected Approval Detail view */}
        <div className="flex-1 bg-slate-900/20 border border-slate-900 rounded-2xl p-6 overflow-y-auto">
          {(() => {
            const selectedApproval = allApprovals.find((a) => a.id === selectedApprovalId);
            if (!selectedApproval) {
              return (
                <div className="h-full flex flex-col items-center justify-center text-center gap-3">
                  <Shield className="h-10 w-10 text-slate-850" />
                  <h3 className="text-sm font-semibold text-slate-400">请在左侧选择一个安全核签工单</h3>
                  <p className="text-xs text-slate-600 max-w-[280px]">
                    选择工单后，此处将全量展示拦截现场的业务上下文、参数序列、及管理员审批决策动作。
                  </p>
                </div>
              );
            }

            const deadlineObj = new Date(selectedApproval.deadline);
            const isExpired = new Date() > deadlineObj;
            const formattedPayload = JSON.stringify(
              selectedApproval.actionPayload?.args || selectedApproval.actionPayload || {},
              null,
              2,
            );

            const statusBadges =
              {
                waiting: 'bg-amber-500/10 text-amber-400 border-amber-500/30 shadow-lg shadow-amber-500/5',
                approved: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30',
                rejected: 'bg-rose-500/10 text-rose-400 border-rose-500/30',
                expired: 'bg-slate-800 text-slate-500 border-transparent',
              }[selectedApproval.status as 'waiting' | 'approved' | 'rejected' | 'expired'] || '';

            return (
              <div className="space-y-6">
                {/* Top detail head */}
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-4 border-b border-slate-800">
                  <div className="space-y-1">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-bold text-slate-100 font-mono">工单: {selectedApproval.id}</span>
                      <span className={`text-xs font-bold px-2.5 py-0.5 rounded border ${statusBadges}`}>
                        {selectedApproval.status === 'waiting'
                          ? '待审批 (Waiting)'
                          : selectedApproval.status === 'approved'
                            ? '已核准 (Approved)'
                            : selectedApproval.status === 'rejected'
                              ? '已驳回 (Rejected)'
                              : '已超时 (Expired)'}
                      </span>
                    </div>
                    <p className="text-xs text-slate-500">
                      拦截触发时间: {new Date(selectedApproval.createdAt).toLocaleString()}
                    </p>
                  </div>
                </div>

                {/* Detail metadata cards */}
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <Card className="bg-slate-900 border-slate-850">
                    <CardContent className="p-4 space-y-1.5">
                      <span className="text-[10px] text-slate-500 font-mono tracking-wider uppercase block">
                        会话通道 (Thread Session)
                      </span>
                      <span className="text-xs font-semibold text-slate-300 block font-mono leading-relaxed truncate">
                        {selectedApproval.threadId}
                      </span>
                    </CardContent>
                  </Card>
                  <Card className="bg-slate-900 border-slate-850">
                    <CardContent className="p-4 space-y-1.5">
                      <span className="text-[10px] text-slate-500 font-mono tracking-wider uppercase block">
                        截止自动释放日期 (Deadline)
                      </span>
                      <span
                        className={`text-xs font-semibold block font-mono leading-relaxed ${isExpired && selectedApproval.status === 'waiting' ? 'text-rose-400' : 'text-slate-300'}`}
                      >
                        {deadlineObj.toLocaleString()}{' '}
                        {isExpired && selectedApproval.status === 'waiting' && ' [已超时]'}
                      </span>
                    </CardContent>
                  </Card>
                </div>

                {/* JSON Payload arguments */}
                <div className="space-y-2">
                  <span className="text-[10px] text-slate-500 font-mono tracking-wider uppercase block font-semibold">
                    拦截动作及物理参数 (Action Payload Arguments)
                  </span>
                  <div className="bg-slate-950 p-4 rounded-xl border border-slate-850 font-mono text-xs leading-relaxed text-indigo-300 whitespace-pre-wrap max-h-60 overflow-y-auto shadow-inner">
                    {formattedPayload}
                  </div>
                </div>

                {/* Action desk if status is waiting */}
                {selectedApproval.status === 'waiting' ? (
                  <div className="space-y-4 pt-4 border-t border-slate-800">
                    <div className="space-y-2">
                      <span className="text-[11px] text-slate-400 font-semibold uppercase font-sans tracking-wide block">
                        审核操作理由 (可留空，驳回时用户可见)
                      </span>
                      <Input
                        type="text"
                        value={rejectionInput}
                        onChange={(e) => setRejectionReason(e.target.value)}
                        placeholder="核准放行可留空。若驳回建议在此处输入具体的驳回原因..."
                        className="w-full bg-slate-950 text-xs py-2 border-slate-850 focus-visible:ring-indigo-500 text-slate-100 rounded-xl placeholder-slate-600"
                      />
                    </div>

                    <div className="flex gap-4">
                      <Button
                        onClick={async () => {
                          const actionId = selectedApproval.id;
                          await handleApprovalAction(actionId, 'approve');
                          // 强制切回聊天面板，前端会自动连接 SSE 订阅恢复决策流
                          setActiveTab('CHAT_DESK');
                        }}
                        disabled={isSubmitting}
                        className="flex-1 bg-emerald-600 hover:bg-emerald-500 text-white rounded-xl h-11 text-xs font-bold transition flex items-center justify-center space-x-1.5 shadow-lg shadow-emerald-600/10"
                      >
                        {isSubmitting ? (
                          <Loader2 className="h-4 w-4 animate-spin" />
                        ) : (
                          <CheckCircle2 className="h-4.5 w-4.5" />
                        )}
                        <span>核准通过此申请 (Approve)</span>
                      </Button>
                      <Button
                        onClick={async () => {
                          const actionId = selectedApproval.id;
                          await handleApprovalAction(actionId, 'reject');
                          setActiveTab('CHAT_DESK');
                        }}
                        disabled={isSubmitting}
                        variant="destructive"
                        className="flex-1 bg-rose-600 hover:bg-rose-500 text-white rounded-xl h-11 text-xs font-bold transition flex items-center justify-center space-x-1.5 shadow-lg shadow-rose-600/10"
                      >
                        {isSubmitting ? (
                          <Loader2 className="h-4 w-4 animate-spin" />
                        ) : (
                          <XCircle className="h-4.5 w-4.5" />
                        )}
                        <span>驳回此高危动作 (Reject)</span>
                      </Button>
                    </div>
                  </div>
                ) : (
                  <div className="p-4 bg-slate-900 border border-slate-850 rounded-xl space-y-1">
                    <span className="text-[10px] text-slate-500 font-mono tracking-wider uppercase block">
                      工单审计回执
                    </span>
                    <p className="text-xs text-slate-300 font-medium leading-relaxed font-sans">
                      本工单已被管理员处理完成，处理决议：
                      <strong
                        className={`font-bold ${selectedApproval.status === 'approved' ? 'text-emerald-400' : 'text-rose-400'}`}
                      >
                        {selectedApproval.status === 'approved'
                          ? '已核准放行'
                          : selectedApproval.status === 'rejected'
                            ? '已驳回动作'
                            : '已被系统自动超时拦截'}
                      </strong>
                      。
                    </p>
                    {selectedApproval.actionPayload?.rejectionReason && (
                      <p className="text-xs text-slate-500 mt-2 font-mono">
                        理由/说明: &quot;{selectedApproval.actionPayload.rejectionReason}&quot;
                      </p>
                    )}
                  </div>
                )}
              </div>
            );
          })()}
        </div>
      </div>
    </div>
  );
}
