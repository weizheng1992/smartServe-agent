import { describe, expect, it } from 'vitest';
import { fmtMoney, orderStatusMeta } from './format';

// 金额诚实律(merchant-admin.md §1.4)单点钉:缺值/坏值「—」,严禁假 ¥0.00/¥NaN。
// 此前同一律在 6 个文件 4 种方言,orders-tab 一处裸奔(Number(null)===0 未挡)。
describe('fmtMoney(全站金额单点)', () => {
  it('数值照常 toFixed(2);0 是真零照常渲染', () => {
    expect(fmtMoney(99)).toBe('99.00');
    expect(fmtMoney('12.5')).toBe('12.50');
    expect(fmtMoney(0)).toBe('0.00');
  });

  it('缺值/坏值诚实「—」:null/undefined/空串/NaN 绝不渲染 ¥0.00 或 ¥NaN', () => {
    expect(fmtMoney(null)).toBe('—');
    expect(fmtMoney(undefined)).toBe('—');
    expect(fmtMoney('')).toBe('—');
    expect(fmtMoney('abc')).toBe('—');
    expect(fmtMoney(Number.NaN)).toBe('—');
  });

  it('trim 变体:坐席上下文栏去整 .00(展示差异为显式声明,非第四种方言)', () => {
    expect(fmtMoney(128, true)).toBe('128');
    expect(fmtMoney(128.5, true)).toBe('128.50');
    expect(fmtMoney(null, true)).toBe('—');
  });
});

describe('orderStatusMeta(订单状态正典表)', () => {
  it('DELIVERED 正典「已签收」(此前 4 文件已签收/已送达两词漂移)', () => {
    expect(orderStatusMeta('DELIVERED').label).toBe('已签收');
    expect(orderStatusMeta('CANCELLED').label).toBe('已取消');
    expect(orderStatusMeta('COMPLETED').label).toBe('已完成');
  });

  it('未知状态诚实兜底:原样展示枚举值不编造', () => {
    expect(orderStatusMeta('SOMETHING_NEW').label).toBe('SOMETHING_NEW');
    expect(orderStatusMeta('SOMETHING_NEW').cls).toContain('slate');
  });
});
