'use client';

import type React from 'react';
import type { RichCardBlock } from 'types';
import { CartCard } from './CartCard';
import { DamageAssessmentCard } from './DamageAssessmentCard';
import { InteractiveProductCard } from './InteractiveProductCard';
import { OrderCard } from './OrderCard';
import { OrderPickerCard } from './OrderPickerCard';
import { ProductRankingCard } from './ProductRankingCard';
import { QuickReplies } from './QuickReplies';
import { RefundConfirmationCard } from './RefundConfirmationCard';
import { StepProgressCard } from './StepProgressCard';
import { TrackingTimeline } from './TrackingTimeline';

export interface RichCardRendererProps {
  cards?: RichCardBlock[];
  onAction?: (action: string, payload?: Record<string, unknown>) => void;
}

const CardSkeleton: React.FC<{ title?: string }> = ({ title }) => (
  <div className="my-2 max-w-md animate-pulse rounded-xl border border-slate-700/50 bg-slate-900/60 p-4 text-slate-100 shadow-lg">
    <div className="flex items-center gap-2.5 border-b border-slate-800 pb-3">
      <div className="h-7 w-7 rounded-lg bg-slate-800" />
      <div className="flex-1 space-y-1.5">
        <div className="h-3.5 w-1/3 rounded bg-slate-800" />
        <div className="h-2.5 w-1/2 rounded bg-slate-850" />
      </div>
      <div className="h-5 w-14 rounded-full bg-slate-800" />
    </div>
    <div className="my-3 space-y-2">
      <div className="h-10 w-full rounded-lg bg-slate-800/60" />
      <div className="h-10 w-full rounded-lg bg-slate-800/40" />
    </div>
    <div className="mt-3 flex gap-2 border-t border-slate-800 pt-2">
      <div className="h-8 flex-1 rounded-lg bg-slate-800" />
      <div className="h-8 flex-1 rounded-lg bg-slate-800/70" />
    </div>
  </div>
);

export const RichCardRenderer: React.FC<RichCardRendererProps> = ({ cards, onAction }) => {
  if (!cards || cards.length === 0) return null;

  return (
    <div className="flex flex-col gap-2.5 my-2">
      {cards.map((card, idx) => {
        const key = card.id || `card_item_${idx}`;
        if (card.hydrationState === 'skeleton') {
          return <CardSkeleton key={key} title={card.type} />;
        }

        switch (card.type) {
          case 'order_card':
            return <OrderCard key={key} data={card.data} onAction={onAction} />;
          case 'order_picker':
            return <OrderPickerCard key={key} data={card.data} onAction={onAction} />;
          case 'tracking_timeline':
            return <TrackingTimeline key={key} data={card.data} />;
          case 'refund_confirmation':
            return (
              <RefundConfirmationCard
                key={key}
                data={card.data}
                onConfirm={() =>
                  onAction?.('confirm_refund', {
                    orderId: card.data.orderId,
                  })
                }
              />
            );
          case 'damage_assessment':
            return <DamageAssessmentCard key={key} data={card.data} />;
          case 'product_ranking':
            return <ProductRankingCard key={key} data={card.data} />;
          case 'cart_card':
            return <CartCard key={key} data={card.data} onAction={onAction} />;
          case 'step_progress':
            return <StepProgressCard key={key} data={card.data} onAction={onAction} />;
          case 'interactive_product':
            return <InteractiveProductCard key={key} data={card.data} onAction={onAction} />;
          case 'quick_replies':
            return <QuickReplies key={key} data={card.data} onSelectOption={onAction} />;
          default:
            return null;
        }
      })}
    </div>
  );
};
