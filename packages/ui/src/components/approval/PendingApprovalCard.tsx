import type React from 'react';
import type { Approval } from 'types';
import {
  Activity,
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  Clock,
  DollarSign,
  Layers,
  Loader2,
  MessageSquare,
  Package,
  ShieldAlert,
  Truck,
  User,
  XCircle,
} from '../icons';
import { Badge } from '../ui/badge';
import { Button } from '../ui/button';
import { Card, CardContent, CardHeader } from '../ui/card';
import { Input } from '../ui/input';
import { ApprovalRiskBadge } from './ApprovalRiskBadge';
import { getApprovalContextData } from './approvalUtils';

export interface PendingApprovalCardProps {
  approval: Approval;
  rejectionReason?: string;
  setRejectionReason?: (reason: string) => void;
  isSubmitting?: boolean;
  onApprove: (approvalId: string) => Promise<void> | void;
  onReject: (approvalId: string) => Promise<void> | void;
  onOpenChat?: (approval: Approval) => void;
  onInspect?: (approval: Approval) => void;
  className?: string;
}

export function PendingApprovalCard({
  approval,
  rejectionReason = '',
  setRejectionReason,
  isSubmitting = false,
  onApprove,
  onReject,
  onOpenChat,
  onInspect,
  className = '',
}: PendingApprovalCardProps) {
  const context = getApprovalContextData(approval);
  const { category } = context;

  const headerConfig = {
    refund: {
      border: 'border-rose-500/40 hover:border-rose-500/60',
      headerBg: 'bg-rose-500/10 border-rose-500/20 text-rose-300',
      icon: <DollarSign className="h-4 w-4 text-rose-400 animate-pulse" />,
      typeLabel: '资金退款审核 (Refund Gate)',
    },
    address: {
      border: 'border-amber-500/40 hover:border-amber-500/60',
      headerBg: 'bg-amber-500/10 border-amber-500/20 text-amber-300',
      icon: <Truck className="h-4 w-4 text-amber-400 animate-pulse" />,
      typeLabel: '地址变更审核 (Address Change)',
    },
    human: {
      border: 'border-indigo-500/40 hover:border-indigo-500/60',
      headerBg: 'bg-indigo-500/10 border-indigo-500/20 text-indigo-300',
      icon: <MessageSquare className="h-4 w-4 text-indigo-400 animate-pulse" />,
      typeLabel: '人工客服接管 (Human Support)',
    },
    generic: {
      border: 'border-slate-800 hover:border-slate-700',
      headerBg: 'bg-slate-900 border-slate-800 text-slate-300',
      icon: <Activity className="h-4 w-4 text-slate-400" />,
      typeLabel: approval.actionType || '安全操作核准',
    },
  }[category];

  return (
    <Card className={`bg-slate-900 overflow-hidden shadow-xl transition-all ${headerConfig.border} ${className}`}>
      {/* 🏷️ Header */}
      <CardHeader
        className={`px-5 py-3.5 border-b flex flex-row justify-between items-center space-y-0 ${headerConfig.headerBg}`}
      >
        <div className="flex items-center space-x-2">
          {headerConfig.icon}
          <span className="text-xs font-bold uppercase tracking-wider font-mono">{headerConfig.typeLabel}</span>
        </div>
        <ApprovalRiskBadge actionType={approval.actionType} status={approval.status} />
      </CardHeader>

      {/* 📦 Main Body */}
      <CardContent className="p-5 space-y-4">
        {/* 🌐 Base Context Metadata */}
        <div className="grid grid-cols-2 gap-2 text-xs bg-slate-950/60 border border-slate-850/80 p-3 rounded-xl">
          <div>
            <span className="text-[10px] text-slate-500 uppercase tracking-wider block font-mono">商户租户</span>
            <span className="font-mono text-indigo-300 font-bold uppercase">{approval.businessId || 'ecommerce'}</span>
          </div>
          <div>
            <span className="text-[10px] text-slate-500 uppercase tracking-wider block font-mono">工单 ID</span>
            <span className="font-mono text-slate-300">{approval.id.substring(0, 10)}...</span>
          </div>
          <div className="col-span-2 flex justify-between items-center pt-1 border-t border-slate-850/60">
            <span className="text-[10px] text-slate-500 font-mono">
              Thread: <span className="text-slate-400 font-mono">{approval.threadId}</span>
            </span>
            {approval.deadline && (
              <span className="text-[10px] text-amber-400/90 font-mono flex items-center gap-1">
                <Clock className="h-3 w-3" />
                {new Date(approval.deadline).toLocaleTimeString([], {
                  hour: '2-digit',
                  minute: '2-digit',
                })}
              </span>
            )}
          </div>
        </div>

        {/* 💬 Context: User Input & Trigger Reason */}
        {(context.reason || context.userInput) && (
          <div className="space-y-2">
            {context.reason && (
              <div className="bg-amber-950/20 border border-amber-500/30 rounded-xl p-3 flex items-start gap-2">
                <AlertTriangle className="h-4 w-4 text-amber-400 shrink-0 mt-0.5" />
                <div className="text-xs">
                  <span className="font-bold text-amber-300 block mb-0.5">拦截与风控原因</span>
                  <span className="text-slate-300 leading-relaxed">{context.reason}</span>
                </div>
              </div>
            )}

            {context.userInput && (
              <div className="bg-slate-950 border border-slate-850 rounded-xl p-3 space-y-1">
                <span className="text-[10px] font-bold text-slate-500 uppercase tracking-wider flex items-center gap-1">
                  <User className="h-3 w-3 text-slate-400" /> 用户原始诉求 / 上下文
                </span>
                <p className="text-xs text-indigo-200 font-mono bg-indigo-950/20 p-2 rounded-lg border border-indigo-500/20">
                  &quot;{context.userInput}&quot;
                </p>
              </div>
            )}
          </div>
        )}

        {/* 🎨 Type-Specific Specialized Details */}
        {category === 'refund' && (
          <div className="bg-rose-950/20 border border-rose-500/30 rounded-xl p-3.5 space-y-2.5">
            <div className="flex items-center justify-between">
              <span className="text-[10px] font-bold text-rose-400 uppercase tracking-wider flex items-center gap-1 font-mono">
                <DollarSign className="h-3.5 w-3.5" /> 退款标的与订单详情
              </span>
              {context.orderId && (
                <Badge
                  variant="outline"
                  className="font-mono text-[10px] bg-slate-950 border-rose-500/40 text-rose-300"
                >
                  {context.orderId}
                </Badge>
              )}
            </div>
            {context.refundAmount !== undefined && (
              <div className="bg-slate-950/80 border border-rose-500/20 p-2.5 rounded-lg flex items-baseline justify-between">
                <span className="text-xs text-slate-400">核准退款金额:</span>
                <span className="text-base font-bold font-mono text-rose-400">
                  ¥ {Number(context.refundAmount).toFixed(2)}
                </span>
              </div>
            )}
          </div>
        )}

        {category === 'address' && (
          <div className="bg-amber-950/20 border border-amber-500/30 rounded-xl p-3.5 space-y-2.5">
            <div className="flex items-center justify-between">
              <span className="text-[10px] font-bold text-amber-400 uppercase tracking-wider flex items-center gap-1 font-mono">
                <Package className="h-3.5 w-3.5" /> 配送地址变更比对
              </span>
              {context.orderId && (
                <Badge
                  variant="outline"
                  className="font-mono text-[10px] bg-slate-950 border-amber-500/40 text-amber-300"
                >
                  {context.orderId}
                </Badge>
              )}
            </div>

            <div className="space-y-1.5 text-xs font-mono">
              {context.oldAddress && (
                <div className="bg-slate-950/80 border border-slate-850 p-2 rounded-lg text-slate-400 line-through">
                  原地址: {context.oldAddress}
                </div>
              )}
              {context.newAddress && (
                <div className="bg-amber-950/40 border border-amber-500/30 p-2 rounded-lg text-amber-200 flex items-start gap-1.5 font-bold">
                  <ArrowRight className="h-3.5 w-3.5 text-amber-400 shrink-0 mt-0.5" />
                  <span>新地址: {context.newAddress}</span>
                </div>
              )}
              {(context.recipientName || context.phone) && (
                <div className="text-[11px] text-slate-400 pt-1 flex gap-3">
                  {context.recipientName && (
                    <span>
                      收件人: <strong className="text-slate-200">{context.recipientName}</strong>
                    </span>
                  )}
                  {context.phone && (
                    <span>
                      电话: <strong className="text-slate-200">{context.phone}</strong>
                    </span>
                  )}
                </div>
              )}
            </div>
          </div>
        )}

        {category === 'human' && (
          <div className="bg-indigo-950/20 border border-indigo-500/30 rounded-xl p-3.5 space-y-2.5">
            <span className="text-[10px] font-bold text-indigo-400 uppercase tracking-wider flex items-center gap-1 font-mono">
              <MessageSquare className="h-3.5 w-3.5" /> 人工客服工单接管状态
            </span>
            <p className="text-xs text-slate-300 leading-relaxed">
              AI 智能助理已暂停自动答复。您可以点击下方按钮进入独立 IM 聊天室，或直接核准/驳回。
            </p>
          </div>
        )}

        {/* 📋 Extra Arguments (if any remaining) */}
        {Object.keys(context.extraArgs).length > 0 && (
          <div className="bg-slate-950 border border-slate-850 rounded-xl p-3 space-y-1.5">
            <span className="text-[9px] font-bold text-slate-500 uppercase tracking-widest block font-mono">
              EXTRA ACTION PAYLOAD
            </span>
            <div className="text-xs font-mono text-slate-300 space-y-1 overflow-x-auto">
              {Object.entries(context.extraArgs).map(([k, v]) => (
                <div key={k} className="flex gap-2">
                  <span className="text-slate-500">{k}:</span>
                  <span className="text-indigo-300">{typeof v === 'object' ? JSON.stringify(v) : String(v)}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* ⚡ Action Buttons & Rejection Input */}
        <div className="space-y-2 pt-1 border-t border-slate-850">
          <div className="flex gap-2">
            {onInspect && (
              <Button
                type="button"
                onClick={() => onInspect(approval)}
                className="flex-1 h-8 text-[11px] font-bold bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-200 rounded-xl flex items-center justify-center gap-1.5 transition shadow-sm"
              >
                <Layers className="h-3.5 w-3.5 text-indigo-400" />
                <span>🔍 触发归因与全景排查</span>
              </Button>
            )}

            {onOpenChat && (
              <Button
                type="button"
                onClick={() => onOpenChat(approval)}
                className="flex-1 h-8 text-[11px] font-bold bg-indigo-600/30 hover:bg-indigo-600/50 border border-indigo-500/40 text-indigo-200 rounded-xl flex items-center justify-center gap-1.5 transition"
              >
                <MessageSquare className="h-3.5 w-3.5 text-indigo-400" />
                <span>💬 客服接管</span>
              </Button>
            )}
          </div>

          {setRejectionReason && (
            <Input
              type="text"
              value={rejectionReason}
              onChange={(e) => setRejectionReason(e.target.value)}
              placeholder="驳回请在此输入拒绝理由..."
              className="bg-slate-950 border-slate-850 text-slate-100 placeholder-slate-600 focus-visible:ring-indigo-500 text-xs h-8"
            />
          )}

          <div className="flex gap-2 pt-1">
            <Button
              type="button"
              onClick={() => onApprove(approval.id)}
              disabled={isSubmitting}
              className="flex-1 h-8 text-[11px] font-bold bg-emerald-600 hover:bg-emerald-500 text-white rounded-xl flex items-center justify-center gap-1.5"
            >
              {isSubmitting ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <>
                  <CheckCircle2 className="h-3.5 w-3.5" />
                  <span>核准通过</span>
                </>
              )}
            </Button>
            <Button
              type="button"
              onClick={() => onReject(approval.id)}
              disabled={isSubmitting}
              className="flex-1 h-8 text-[11px] font-bold bg-rose-600 hover:bg-rose-500 text-white rounded-xl flex items-center justify-center gap-1.5"
            >
              {isSubmitting ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <>
                  <XCircle className="h-3.5 w-3.5" />
                  <span>驳回申请</span>
                </>
              )}
            </Button>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
