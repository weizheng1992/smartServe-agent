import React from 'react';
import { Badge, Button, DetailDrawer } from 'ui';
import type { AuditRecord } from '../types';

export interface AuditDetailDrawerProps {
  isOpen: boolean;
  onClose: () => void;
  audit: AuditRecord | null;
  onResolveAction: (action: 'approved' | 'rejected') => void;
  isActing: boolean;
}

export function AuditDetailDrawer({ isOpen, onClose, audit, onResolveAction, isActing }: AuditDetailDrawerProps) {
  if (!audit) return null;

  return (
    <DetailDrawer
      isOpen={isOpen}
      onClose={onClose}
      title={`风控审批工单详情: ${audit.id}`}
      subtitle={`会话 ID: ${audit.threadId} | 商户: ${audit.businessId.toUpperCase()}`}
      badge={
        audit.status === 'waiting' ? (
          <Badge variant="outline" className="bg-amber-50 text-amber-800 border-amber-200">
            等待审批决议
          </Badge>
        ) : (
          <Badge variant="secondary">{audit.status}</Badge>
        )
      }
      footer={
        audit.status === 'waiting' ? (
          <div className="flex items-center gap-2">
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={isActing}
              onClick={() => onResolveAction('rejected')}
              className="text-xs font-medium bg-rose-50 text-rose-700 hover:bg-rose-100 border-rose-200"
            >
              平台强制驳回
            </Button>
            <Button
              type="button"
              size="sm"
              disabled={isActing}
              onClick={() => onResolveAction('approved')}
              className="text-xs font-medium bg-emerald-600 hover:bg-emerald-700 text-white shadow-xs"
            >
              平台直接核准通过
            </Button>
          </div>
        ) : null
      }
    >
      <div className="space-y-4">
        <div className="bg-slate-50 border border-slate-200 rounded-xl p-4">
          <div className="text-xs font-semibold text-slate-700 mb-2">执行动作入参 Payload</div>
          <pre className="text-xs font-mono bg-white p-3 rounded-lg border border-slate-200 overflow-x-auto text-slate-800">
            {JSON.stringify(audit.actionPayload, null, 2)}
          </pre>
        </div>

        <div className="grid grid-cols-2 gap-3 text-xs">
          <div className="p-3 bg-slate-50 border border-slate-200 rounded-xl">
            <span className="text-slate-400">审批提交时间:</span>
            <div className="font-semibold text-slate-800 mt-0.5">{audit.createdAt}</div>
          </div>
          <div className="p-3 bg-slate-50 border border-slate-200 rounded-xl">
            <span className="text-slate-400">决议时间:</span>
            <div className="font-semibold text-slate-800 mt-0.5">{audit.resolvedAt || '尚未处理'}</div>
          </div>
        </div>
      </div>
    </DetailDrawer>
  );
}
