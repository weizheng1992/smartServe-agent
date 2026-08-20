"use client";

import React from "react";
import type { QuickRepliesData } from "types";
import { Sparkles } from "../../icons";

export interface QuickRepliesProps {
  data: QuickRepliesData;
  onSelectOption?: (action: string, payload?: Record<string, unknown>) => void;
}

export const QuickReplies: React.FC<QuickRepliesProps> = ({
  data,
  onSelectOption,
}) => {
  if (!data?.options || data.options.length === 0) return null;

  return (
    <div className="my-2.5 space-y-1.5">
      {data.title && (
        <div className="flex items-center gap-1 text-[11px] font-medium text-slate-400">
          <Sparkles className="h-3 w-3 text-indigo-400" />
          {data.title}
        </div>
      )}
      <div className="flex flex-wrap gap-1.5">
        {data.options.map((opt, idx) => (
          <button
            key={idx}
            type="button"
            onClick={() => onSelectOption?.(opt.action, opt.payload)}
            className="group flex items-center gap-1.5 rounded-full border border-indigo-500/30 bg-indigo-950/40 px-3 py-1.5 text-xs text-indigo-200 transition-all hover:border-indigo-400 hover:bg-indigo-600/20 hover:text-white"
          >
            <span>{opt.label}</span>
          </button>
        ))}
      </div>
    </div>
  );
};
