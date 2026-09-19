import '@testing-library/jest-dom/vitest';
import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { EffectCards } from './effect-cards';

describe('EffectCards', () => {
  it('无数据时诚实占位(— 与 ¥0)', () => {
    render(<EffectCards effect={null} />);
    expect(screen.getByText('进行中活动').previousElementSibling).toHaveTextContent('—');
    expect(screen.getByText('累计核销单数').previousElementSibling).toHaveTextContent('—');
    expect(screen.getByText('累计优惠金额').previousElementSibling).toHaveTextContent('¥0');
  });

  it('有数据时渲染真实统计值', () => {
    render(<EffectCards effect={{ activePromotions: 2, redemptions: 5, totalDiscount: 1234 }} />);
    expect(screen.getByText('2')).toBeInTheDocument();
    expect(screen.getByText('5')).toBeInTheDocument();
    expect(screen.getByText(/1,234/)).toBeInTheDocument();
  });
});
