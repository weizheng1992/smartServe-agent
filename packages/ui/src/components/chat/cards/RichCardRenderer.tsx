'use client';

import type React from 'react';
import type { RichCardBlock } from 'types';
import { CartCard } from './CartCard';
import { DamageAssessmentCard } from './DamageAssessmentCard';
import { OrderCard } from './OrderCard';
import { OrderPickerCard } from './OrderPickerCard';
import { ProductRankingCard } from './ProductRankingCard';
import { QuickReplies } from './QuickReplies';
import { RefundConfirmationCard } from './RefundConfirmationCard';
import { TrackingTimeline } from './TrackingTimeline';

export interface RichCardRendererProps {
  cards?: RichCardBlock[];
  onAction?: (action: string, payload?: Record<string, unknown>) => void;
}

export const RichCardRenderer: React.FC<RichCardRendererProps> = ({ cards, onAction }) => {
  if (!cards || cards.length === 0) return null;

  return (
    <div className="flex flex-col gap-2.5 my-2">
      {cards.map((card, idx) => {
        switch (card.type) {
          case 'order_card':
            return <OrderCard key={idx} data={card.data} onAction={onAction} />;
          case 'order_picker':
            return <OrderPickerCard key={idx} data={card.data} onAction={onAction} />;
          case 'tracking_timeline':
            return <TrackingTimeline key={idx} data={card.data} />;
          case 'refund_confirmation':
            return (
              <RefundConfirmationCard
                key={idx}
                data={card.data}
                onConfirm={() =>
                  onAction?.('confirm_refund', {
                    orderId: card.data.orderId,
                  })
                }
              />
            );
          case 'damage_assessment':
            return <DamageAssessmentCard key={idx} data={card.data} />;
          case 'product_ranking':
            return <ProductRankingCard key={idx} data={card.data} />;
          case 'cart_card':
            return <CartCard key={idx} data={card.data} onAction={onAction} />;
          case 'quick_replies':
            return <QuickReplies key={idx} data={card.data} onSelectOption={onAction} />;
          default:
            return null;
        }
      })}
    </div>
  );
};
