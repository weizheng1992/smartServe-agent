import { describe, expect, it } from 'vitest';
import { fmtMoney } from './format';

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
});
