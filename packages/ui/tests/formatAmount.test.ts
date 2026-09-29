// 金额统一口径钉子(2026-09-29 夜审):四处聊天卡逐字拷贝的 formatAmount 把
// null/undefined/坏值兜底渲染 '0.00' —— 缺金额显示成假 ¥0.00,正是
// merchant-admin.md §1.4 点名必挡的事故形态(Number(null)===0 陷阱同源)。
// 收口为 lib/utils 单一实现后,坏值一律诚实「—」。
import { describe, expect, it } from 'bun:test';
import { formatAmount } from '../src/lib/utils';

describe('formatAmount 诚实降级', () => {
  it('有限数值正常格式化,0 是合法金额照常显示', () => {
    expect(formatAmount(1234.5)).toBe('1234.50');
    expect(formatAmount(0)).toBe('0.00');
    expect(formatAmount(-8.1)).toBe('-8.10');
  });

  it('缺值/坏值/NaN/Infinity 一律「—」,绝不渲染假 0.00 或 "NaN" 字面量', () => {
    expect(formatAmount(null)).toBe('—');
    expect(formatAmount(undefined)).toBe('—');
    expect(formatAmount('')).toBe('—');
    expect(formatAmount('暂无')).toBe('—');
    expect(formatAmount(Number.NaN)).toBe('—');
    expect(formatAmount(Number.POSITIVE_INFINITY)).toBe('—');
    expect(formatAmount({})).toBe('—');
  });

  it('带货币符号/千分位的字符串金额照常解析', () => {
    expect(formatAmount('¥1,234.50')).toBe('1234.50');
    expect(formatAmount('88')).toBe('88.00');
  });
});
