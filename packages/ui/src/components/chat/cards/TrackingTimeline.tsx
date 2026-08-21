'use client';

import type React from 'react';
import type { TrackingTimelineData } from 'types';
import { Truck } from '../../icons';

export interface TrackingTimelineProps {
  data: TrackingTimelineData;
}

export const TrackingTimeline: React.FC<TrackingTimelineProps> = ({ data }) => {
  return (
    <div className="my-2 max-w-md overflow-hidden rounded-xl border border-slate-700/60 bg-gradient-to-b from-slate-850 to-slate-900/90 p-4 text-slate-100 shadow-xl backdrop-blur-md">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-slate-750/70 pb-3">
        <div className="flex items-center gap-2">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-blue-500/10 text-blue-400">
            <Truck className="h-4 w-4" />
          </div>
          <div>
            <div className="text-xs font-semibold text-slate-400">{data.carrier} 实时物流追踪</div>
            <div className="font-mono text-sm font-bold text-blue-300">{data.trackingNumber}</div>
          </div>
        </div>
        <span className="inline-flex items-center rounded-full bg-blue-500/10 px-2.5 py-1 text-xs font-medium text-blue-400 ring-1 ring-inset ring-blue-500/20">
          {data.currentStatus}
        </span>
      </div>

      {/* Timeline nodes */}
      <div className="relative mt-4 space-y-4 pl-4 before:absolute before:bottom-2 before:left-[21px] before:top-2 before:w-0.5 before:bg-slate-700">
        {data.timeline.map((node, idx) => {
          const isLatest = idx === 0;
          return (
            <div key={idx} className="relative flex items-start gap-3">
              <div
                className={`relative z-10 flex h-3.5 w-3.5 shrink-0 items-center justify-center rounded-full ${
                  isLatest ? 'bg-blue-500 ring-4 ring-blue-500/20' : 'bg-slate-600'
                }`}
              />
              <div className="flex-1 text-xs">
                <div className="flex items-center justify-between">
                  <span className={`font-semibold ${isLatest ? 'text-blue-300' : 'text-slate-300'}`}>
                    {node.location || '转运中心'}
                  </span>
                  <span className="font-mono text-[11px] text-slate-500">{node.time}</span>
                </div>
                <p className="mt-1 text-slate-400 leading-relaxed">{node.description}</p>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
};
