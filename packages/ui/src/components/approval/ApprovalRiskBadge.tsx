import type React from 'react';
import { Badge } from '../ui/badge';

export interface ApprovalRiskBadgeProps {
  actionType?: string | null;
  status?: string | null;
  riskLevel?: string | null;
  className?: string;
}

export function ApprovalRiskBadge({ actionType, status, riskLevel, className }: ApprovalRiskBadgeProps) {
  if (riskLevel === 'high' || riskLevel === 'critical') {
    return (
      <Badge
        variant="outline"
        className={`bg-rose-500/10 text-rose-500 border-rose-500/30 text-[10px] font-mono px-2 py-0.5 ${className || ''}`}
      >
        高风险拦截
      </Badge>
    );
  }

  if (riskLevel === 'medium') {
    return (
      <Badge
        variant="outline"
        className={`bg-amber-500/10 text-amber-500 border-amber-500/30 text-[10px] font-mono px-2 py-0.5 ${className || ''}`}
      >
        中风险关注
      </Badge>
    );
  }

  if (riskLevel === 'low') {
    return (
      <Badge
        variant="outline"
        className={`bg-blue-500/10 text-blue-500 border-blue-500/30 text-[10px] font-mono px-2 py-0.5 ${className || ''}`}
      >
        低风险放行
      </Badge>
    );
  }
  if (status === 'approved') {
    return (
      <Badge
        variant="outline"
        className={`bg-emerald-500/10 text-emerald-400 border-emerald-500/30 text-[10px] font-mono px-2 py-0.5 ${className || ''}`}
      >
        已核准放行
      </Badge>
    );
  }

  if (status === 'rejected') {
    return (
      <Badge
        variant="outline"
        className={`bg-rose-500/10 text-rose-400 border-rose-500/30 text-[10px] font-mono px-2 py-0.5 ${className || ''}`}
      >
        已拒绝驳回
      </Badge>
    );
  }

  if (status === 'expired') {
    return (
      <Badge
        variant="outline"
        className={`bg-slate-800 text-slate-500 border-slate-700 text-[10px] font-mono px-2 py-0.5 ${className || ''}`}
      >
        已超时解挂
      </Badge>
    );
  }

  if (actionType === 'processRefund') {
    return (
      <Badge
        variant="outline"
        className={`bg-rose-500/10 text-rose-400 border-rose-500/30 text-[10px] font-mono px-2 py-0.5 animate-pulse ${className || ''}`}
      >
        资金红线拦截
      </Badge>
    );
  }

  if (actionType === 'changeShippingAddress') {
    return (
      <Badge
        variant="outline"
        className={`bg-amber-500/10 text-amber-400 border-amber-500/30 text-[10px] font-mono px-2 py-0.5 ${className || ''}`}
      >
        高价值地址修改
      </Badge>
    );
  }

  if (actionType === 'human_escalation') {
    return (
      <Badge
        variant="outline"
        className={`bg-indigo-500/10 text-indigo-400 border-indigo-500/30 text-[10px] font-mono px-2 py-0.5 ${className || ''}`}
      >
        人工客服接管
      </Badge>
    );
  }

  return (
    <Badge
      variant="outline"
      className={`bg-amber-500/10 text-amber-400 border-amber-500/30 text-[10px] font-mono px-2 py-0.5 ${className || ''}`}
    >
      待审核核签
    </Badge>
  );
}
