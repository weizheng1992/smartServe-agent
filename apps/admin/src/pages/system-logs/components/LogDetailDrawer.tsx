import React from 'react';
import { DetailDrawer } from 'ui';
import type { SystemLogRecord } from '../types';

export interface LogDetailDrawerProps {
  isOpen: boolean;
  onClose: () => void;
  log: SystemLogRecord | null;
}

export function LogDetailDrawer({ isOpen, onClose, log }: LogDetailDrawerProps) {
  if (!log) return null;

  return (
    <DetailDrawer
      isOpen={isOpen}
      onClose={onClose}
      title={`系统全链路日志详情: ${log.id}`}
      subtitle={`Trace: ${log.traceId} | 耗时: ${log.latencyMs}ms`}
    >
      <div className="space-y-4">
        <div className="grid grid-cols-2 gap-3 text-xs">
          <div className="p-3 bg-slate-50 border border-slate-200 rounded-xl">
            <span className="text-slate-400">商户租户:</span>
            <div className="font-semibold text-slate-800 mt-0.5">{log.businessId}</div>
          </div>
          <div className="p-3 bg-slate-50 border border-slate-200 rounded-xl">
            <span className="text-slate-400">调用状态码:</span>
            <div className="font-semibold text-emerald-600 mt-0.5">{log.statusCode} OK</div>
          </div>
        </div>

        <div className="bg-slate-900 text-slate-200 rounded-xl p-4 font-mono text-xs">
          <div className="text-slate-400 mb-2">{'// Raw Payload / Execution Detail'}</div>
          <pre className="overflow-x-auto text-emerald-400">{JSON.stringify(log.rawDetail, null, 2)}</pre>
        </div>
      </div>
    </DetailDrawer>
  );
}
