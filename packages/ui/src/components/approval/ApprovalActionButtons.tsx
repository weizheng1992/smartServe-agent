import type React from 'react';
import { CheckCircle2, Loader2, XCircle } from '../icons';
import { Button } from '../ui/button';

export interface ApprovalActionButtonsProps {
  approvalId: string;
  isSubmitting: boolean;
  disabled?: boolean;
  onApprove: (approvalId: string) => void | Promise<void>;
  onReject: (approvalId: string) => void | Promise<void>;
  approveText?: string;
  rejectText?: string;
  size?: 'default' | 'sm' | 'lg' | 'icon';
  className?: string;
}

export function ApprovalActionButtons({
  approvalId,
  isSubmitting,
  disabled = false,
  onApprove,
  onReject,
  approveText = '核准放行',
  rejectText = '拒绝驳回',
  size = 'default',
  className = '',
}: ApprovalActionButtonsProps) {
  return (
    <div className={`flex items-center gap-2 ${className}`}>
      <Button
        size={size}
        disabled={disabled || isSubmitting}
        onClick={() => onApprove(approvalId)}
        className="flex-1 bg-emerald-600 hover:bg-emerald-500 text-white font-medium shadow-md shadow-emerald-950/40"
      >
        {isSubmitting ? (
          <Loader2 className="h-4 w-4 animate-spin mr-1.5" />
        ) : (
          <CheckCircle2 className="h-4 w-4 mr-1.5" />
        )}
        {approveText}
      </Button>

      <Button
        size={size}
        variant="outline"
        disabled={disabled || isSubmitting}
        onClick={() => onReject(approvalId)}
        className="flex-1 bg-rose-500/10 hover:bg-rose-500/20 text-rose-300 border-rose-500/30"
      >
        {isSubmitting ? <Loader2 className="h-4 w-4 animate-spin mr-1.5" /> : <XCircle className="h-4 w-4 mr-1.5" />}
        {rejectText}
      </Button>
    </div>
  );
}
