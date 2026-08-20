"use client";

import React from "react";
import type { DamageAssessmentData } from "types";
import { Camera, CheckCircle2, AlertTriangle, AlertOctagon } from "../../icons";

export interface DamageAssessmentCardProps {
  data: DamageAssessmentData;
}

export const DamageAssessmentCard: React.FC<DamageAssessmentCardProps> = ({
  data,
}) => {
  const isSevere = data.damageLevel === "severe";
  const isMinor = data.damageLevel === "minor";

  return (
    <div className="my-2 max-w-md overflow-hidden rounded-xl border border-indigo-500/30 bg-gradient-to-b from-indigo-950/40 to-slate-900/90 p-4 text-slate-100 shadow-xl backdrop-blur-md">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-indigo-500/20 pb-3">
        <div className="flex items-center gap-2">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-indigo-500/10 text-indigo-400">
            <Camera className="h-4 w-4" />
          </div>
          <div>
            <div className="text-xs font-semibold text-indigo-300">
              AI 视觉成色与定责智能评定
            </div>
            <div className="text-xs font-medium text-slate-400">
              置信度: {(data.confidence * 100).toFixed(0)}%
            </div>
          </div>
        </div>
        <span
          className={`inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-xs font-medium ${
            isSevere
              ? "bg-rose-500/10 text-rose-400 ring-1 ring-inset ring-rose-500/20"
              : isMinor
                ? "bg-amber-500/10 text-amber-400 ring-1 ring-inset ring-amber-500/20"
                : "bg-emerald-500/10 text-emerald-400 ring-1 ring-inset ring-emerald-500/20"
          }`}
        >
          {isSevere ? (
            <AlertOctagon className="h-3 w-3" />
          ) : (
            <AlertTriangle className="h-3 w-3" />
          )}
          {isSevere ? "严重破损" : isMinor ? "瑕疵/轻微受损" : "成色良好"}
        </span>
      </div>

      {/* Body & Image Preview */}
      <div className="my-3 space-y-2.5 text-xs">
        {data.imageUrl && (
          <div className="relative overflow-hidden rounded-lg border border-slate-700 bg-slate-950">
            <img
              src={data.imageUrl}
              alt="Uploaded Item"
              className="max-h-48 w-full object-cover"
            />
          </div>
        )}
        <div className="rounded-lg bg-slate-800/60 p-2.5 text-slate-300 leading-relaxed">
          <span className="font-semibold text-slate-200">AI 诊断概述：</span>
          {data.summary}
        </div>
        <div className="flex items-center justify-between text-slate-400 text-[11px]">
          <span>系统建议处置策略:</span>
          <span className="font-semibold text-indigo-300">
            {data.suggestedAction === "auto_refund"
              ? "符合快速秒级赔付标准"
              : data.suggestedAction === "human_review"
                ? "转人工客服专员定责复验"
                : "需寄回仓库质检定损"}
          </span>
        </div>
      </div>
    </div>
  );
};
