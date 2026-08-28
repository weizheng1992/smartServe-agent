'use client';

import React, { useState } from 'react';
import type { StepProgressCardData, StepProgressItem } from 'types';
import { AlertCircle, CheckCircle2, ChevronRight, Clock, FileText, Send } from '../../icons';

export interface StepProgressCardProps {
  data: StepProgressCardData;
  onAction?: (action: string, payload?: Record<string, unknown>) => void;
}

export const StepProgressCard: React.FC<StepProgressCardProps> = ({ data, onAction }) => {
  const steps = data.steps || [];
  const currentStepIdx = data.currentStep ?? 0;
  const [inputValue, setInputValue] = useState('');
  const [selectedOption, setSelectedOption] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);

  const handleSubmitStepAction = (item: StepProgressItem) => {
    if (!item.actionRequired) return;
    setIsSubmitting(true);
    const action = item.actionRequired.submitAction || 'submit_step_action';
    const payload: Record<string, unknown> = {
      ticketId: data.ticketId,
      orderId: data.orderId,
      stepIndex: item.stepIndex,
      actionType: item.actionRequired.actionType,
      value: item.actionRequired.actionType === 'input_text' ? inputValue : selectedOption,
    };

    onAction?.(action, payload);
    setTimeout(() => {
      setIsSubmitting(false);
    }, 400);
  };

  return (
    <div className="my-2 max-w-md overflow-hidden rounded-xl border border-indigo-800/40 bg-gradient-to-b from-slate-900 via-slate-850 to-slate-900 p-4 text-slate-100 shadow-xl backdrop-blur-md transition-all hover:border-indigo-600/60">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-slate-750/70 pb-3">
        <div className="flex items-center gap-2.5">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-indigo-500/10 text-indigo-400">
            <FileText className="h-4 w-4" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <span className="text-sm font-bold text-indigo-300">{data.title || '服务业务流程追踪'}</span>
              {data.orderId && <span className="font-mono text-[11px] text-slate-400">({data.orderId})</span>}
            </div>
            <div className="text-xs text-slate-400">
              当前进行至第 <span className="font-semibold text-indigo-400">{currentStepIdx + 1}</span> /{' '}
              {data.totalSteps || steps.length} 步
            </div>
          </div>
        </div>
        <span className="inline-flex items-center rounded-full bg-indigo-500/10 px-2.5 py-1 text-xs font-medium text-indigo-400 ring-1 ring-inset ring-indigo-500/20">
          业务流转中
        </span>
      </div>

      {/* Steps List */}
      <div className="my-3 space-y-3">
        {steps.map((item, idx) => {
          const isCompleted = item.status === 'completed' || idx < currentStepIdx;
          const isCurrent = item.status === 'current' || idx === currentStepIdx;
          const isUpcoming = !isCompleted && !isCurrent;
          const isError = item.status === 'error';

          return (
            <div
              key={`step_${idx}`}
              className={`relative flex items-start gap-3 rounded-lg p-2.5 transition-all ${
                isCurrent
                  ? 'bg-indigo-950/40 border border-indigo-700/50 shadow-inner'
                  : isCompleted
                    ? 'bg-slate-800/30 border border-slate-700/30'
                    : 'bg-slate-900/40 border border-slate-800/20 opacity-60'
              }`}
            >
              {/* Step Icon */}
              <div className="shrink-0 pt-0.5">
                {isCompleted ? (
                  <div className="flex h-5 w-5 items-center justify-center rounded-full bg-emerald-500/20 text-emerald-400">
                    <CheckCircle2 className="h-4 w-4" />
                  </div>
                ) : isCurrent ? (
                  <div className="relative flex h-5 w-5 items-center justify-center rounded-full bg-indigo-500 text-white font-bold text-[11px] ring-4 ring-indigo-500/20">
                    {idx + 1}
                  </div>
                ) : isError ? (
                  <div className="flex h-5 w-5 items-center justify-center rounded-full bg-rose-500/20 text-rose-400">
                    <AlertCircle className="h-4 w-4" />
                  </div>
                ) : (
                  <div className="flex h-5 w-5 items-center justify-center rounded-full bg-slate-800 text-slate-400 text-[11px]">
                    <Clock className="h-3 w-3" />
                  </div>
                )}
              </div>

              {/* Step Details */}
              <div className="flex-1 min-w-0">
                <div className="flex items-center justify-between">
                  <span
                    className={`text-xs font-semibold ${
                      isCurrent ? 'text-indigo-200' : isCompleted ? 'text-slate-300' : 'text-slate-500'
                    }`}
                  >
                    {item.title}
                  </span>
                  <span
                    className={`text-[10px] ${
                      isCompleted ? 'text-emerald-400' : isCurrent ? 'text-indigo-400 font-medium' : 'text-slate-500'
                    }`}
                  >
                    {isCompleted ? '已完成' : isCurrent ? '处理中' : '待进行'}
                  </span>
                </div>

                {item.description && (
                  <p className="mt-0.5 text-[11px] text-slate-400 leading-relaxed">{item.description}</p>
                )}

                {/* Interactive Action Field on Current Step */}
                {isCurrent && item.actionRequired && (
                  <div className="mt-2.5 pt-2 border-t border-indigo-900/60 flex flex-col gap-2">
                    {item.actionRequired.actionType === 'input_text' && (
                      <div className="flex items-center gap-2">
                        <input
                          type="text"
                          value={inputValue}
                          onChange={(e) => setInputValue(e.target.value)}
                          placeholder={item.actionRequired.placeholder || '请输入相关单号或信息...'}
                          className="flex-1 rounded-md bg-slate-900/90 px-2.5 py-1.5 text-xs text-slate-100 placeholder-slate-500 border border-indigo-700/50 focus:outline-none focus:border-indigo-400"
                        />
                        <button
                          type="button"
                          disabled={isSubmitting || !inputValue.trim()}
                          onClick={() => handleSubmitStepAction(item)}
                          className="flex items-center gap-1 rounded-md bg-indigo-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-indigo-500 disabled:opacity-50 cursor-pointer"
                        >
                          <Send className="h-3 w-3" />
                          {item.actionRequired.buttonLabel || '提交'}
                        </button>
                      </div>
                    )}

                    {item.actionRequired.actionType === 'select_option' && item.actionRequired.options && (
                      <div className="flex flex-wrap gap-1.5">
                        {item.actionRequired.options.map((opt) => (
                          <button
                            key={opt.value}
                            type="button"
                            onClick={() => {
                              setSelectedOption(opt.value);
                              handleSubmitStepAction({
                                ...item,
                                actionRequired: {
                                  ...item.actionRequired!,
                                  actionType: 'select_option',
                                },
                              });
                            }}
                            className={`rounded-md px-2.5 py-1 text-xs border transition-colors cursor-pointer ${
                              selectedOption === opt.value
                                ? 'bg-indigo-600 text-white border-indigo-500'
                                : 'bg-slate-800 text-slate-300 border-slate-700 hover:border-indigo-500/50'
                            }`}
                          >
                            {opt.label}
                          </button>
                        ))}
                      </div>
                    )}

                    {item.actionRequired.actionType === 'confirm_button' && (
                      <button
                        type="button"
                        disabled={isSubmitting}
                        onClick={() => handleSubmitStepAction(item)}
                        className="flex items-center justify-center gap-1.5 rounded-md bg-indigo-600 py-1.5 text-xs font-semibold text-white hover:bg-indigo-500 cursor-pointer"
                      >
                        <ChevronRight className="h-3.5 w-3.5" />
                        {item.actionRequired.buttonLabel || '确认并继续'}
                      </button>
                    )}
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {/* Settled Summary Footer */}
      {data.settledSummary && (
        <div className="mt-2 rounded-lg bg-emerald-950/30 border border-emerald-800/40 p-2 text-xs text-emerald-300 flex items-center gap-1.5">
          <CheckCircle2 className="h-3.5 w-3.5 shrink-0" />
          <span>{data.settledSummary}</span>
        </div>
      )}
    </div>
  );
};
