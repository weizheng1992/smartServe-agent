import { describe, expect, it } from 'vitest';
import { scopeEditableFor, scopeLabel } from './scope';

describe('scopeLabel', () => {
  it('all / 空值 → 全部商品', () => {
    expect(scopeLabel('all', null)).toBe('全部商品');
    expect(scopeLabel(null, null)).toBe('全部商品');
  });

  it('spu 范围优先回显商品标题,查不到回退编码', () => {
    expect(scopeLabel('spu', 'AURORA-SPU-1', { 'AURORA-SPU-1': '越野跑鞋' })).toBe('指定商品:越野跑鞋');
    expect(scopeLabel('spu', 'AURORA-SPU-404', {})).toBe('指定商品:AURORA-SPU-404');
    expect(scopeLabel('spu', null, {})).toBe('指定商品:未设置');
  });

  it('未知范围类型原样展示(诚实呈现)', () => {
    expect(scopeLabel('weird', 'x')).toBe('范围:weird');
  });
});

describe('scopeEditableFor', () => {
  it('券型不可配范围(引擎对券无视范围),满减/折扣可配', () => {
    expect(scopeEditableFor('coupon')).toBe(false);
    expect(scopeEditableFor('full_reduction')).toBe(true);
    expect(scopeEditableFor('discount')).toBe(true);
  });
});
