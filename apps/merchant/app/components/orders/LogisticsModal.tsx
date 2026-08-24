'use client';

import type React from 'react';
import { useState } from 'react';
import type { ThirdPartyOrder } from 'types';

interface LogisticsModalProps {
  isOpen: boolean;
  onClose: () => void;
  order: ThirdPartyOrder | null;
  onOpenChatWithOrder: (orderId: string) => void;
}

export const LogisticsModal: React.FC<LogisticsModalProps> = ({ isOpen, onClose, order, onOpenChatWithOrder }) => {
  const [copied, setCopied] = useState(false);

  if (!isOpen || !order) return null;

  const tracking = order.tracking;
  const trackingNumber = tracking?.trackingNumber || '暂无单号';
  const carrier = tracking?.carrier || '顺丰速运';
  const timeline = tracking?.timeline || [];

  const handleCopy = () => {
    if (tracking?.trackingNumber) {
      navigator.clipboard.writeText(tracking.trackingNumber);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      {/* 遮罩 */}
      <div
        className="fixed inset-0 bg-slate-900/60 backdrop-blur-xs transition-opacity cursor-pointer"
        onClick={onClose}
      />

      <div className="relative bg-white rounded-2xl max-w-lg w-full p-6 shadow-2xl z-10 max-h-[90vh] flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between pb-4 border-b border-slate-200">
          <div className="flex items-center space-x-2">
            <span className="text-xl">🚚</span>
            <div>
              <h3 className="text-base font-bold text-slate-900">物流实时轨迹</h3>
              <p className="text-xs text-slate-500">订单号: {order.orderId}</p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="text-slate-400 hover:text-slate-600 p-1 rounded-lg hover:bg-slate-100"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* 运单核心摘要 Banner */}
        <div className="mt-4 bg-gradient-to-r from-emerald-900 to-slate-900 text-white rounded-xl p-4 shadow-sm">
          <div className="flex items-center justify-between">
            <div className="flex items-center space-x-2">
              <span className="bg-emerald-500 text-white text-xs font-bold px-2.5 py-0.5 rounded-full">{carrier}</span>
              <span className="font-mono text-sm tracking-wider">{trackingNumber}</span>
            </div>
            <button
              type="button"
              onClick={handleCopy}
              className="text-xs bg-white/15 hover:bg-white/25 px-2.5 py-1 rounded-md transition flex items-center space-x-1 cursor-pointer"
            >
              <span>{copied ? '✓ 已复制' : '复制单号'}</span>
            </button>
          </div>

          <div className="mt-3 pt-3 border-t border-white/10 flex items-center justify-between text-xs text-emerald-200">
            <div>
              <span>当前最新状态：</span>
              <strong className="text-white ml-1">{tracking?.status || '运输中'}</strong>
            </div>
            <div className="text-right">
              <span>目的地：</span>
              <span className="text-slate-300 ml-1">{order.shippingAddress.fullAddress.substring(0, 10)}...</span>
            </div>
          </div>
        </div>

        {/* 时间线列表 */}
        <div className="flex-1 overflow-y-auto py-5 space-y-4 pr-1">
          {timeline.length === 0 ? (
            <div className="text-center py-10 text-slate-400 text-xs">包裹正在等待仓库出库揽收中，暂无流转节点...</div>
          ) : (
            <div className="relative pl-6 border-l-2 border-emerald-200 space-y-6 ml-3">
              {timeline.map((node, index) => {
                const isLatest = index === timeline.length - 1 || index === 0;
                return (
                  <div key={node.time + index} className="relative">
                    {/* 节点原点 */}
                    <div
                      className={`absolute -left-[31px] top-0.5 w-4 h-4 rounded-full border-2 bg-white flex items-center justify-center ${
                        isLatest ? 'border-emerald-500 ring-4 ring-emerald-100' : 'border-slate-300'
                      }`}
                    >
                      {isLatest && <div className="w-1.5 h-1.5 rounded-full bg-emerald-600" />}
                    </div>

                    <div>
                      <div className="flex items-center space-x-2">
                        <span className={`text-xs font-bold ${isLatest ? 'text-emerald-700' : 'text-slate-700'}`}>
                          {node.status}
                        </span>
                        <span className="text-[11px] text-slate-400 font-mono">
                          {new Date(node.time).toLocaleString()}
                        </span>
                      </div>

                      {node.location && (
                        <div className="text-[11px] text-slate-500 mt-0.5 font-medium">📍 {node.location}</div>
                      )}

                      <p className="text-xs text-slate-600 mt-1 leading-relaxed bg-slate-50 p-2.5 rounded-lg border border-slate-100">
                        {node.description}
                      </p>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* 底部客服联动 */}
        <div className="pt-3 border-t border-slate-200 flex items-center justify-between gap-3">
          <div className="text-xs text-slate-500">遇到物流延误或包裹破损？</div>
          <button
            type="button"
            onClick={() => {
              onClose();
              onOpenChatWithOrder(order.orderId);
            }}
            className="px-3 py-1.5 text-xs font-bold text-emerald-700 bg-emerald-50 hover:bg-emerald-100 border border-emerald-200 rounded-lg flex items-center space-x-1.5 transition cursor-pointer"
          >
            <span>💬 咨询智能客服极速处理</span>
          </button>
        </div>
      </div>
    </div>
  );
};
