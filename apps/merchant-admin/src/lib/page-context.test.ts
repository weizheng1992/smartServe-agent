import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  clearSelection,
  getSelection,
  getSelectionLabels,
  setSelectionKind,
  subscribe,
  toggleKindId,
} from './page-context';

// page-context 是模块级单例:每例前清空互不污染
beforeEach(() => clearSelection());

describe('page-context(类型化勾选广播库)', () => {
  it('setSelectionKind 按类型存取,空数组即清除该类', () => {
    setSelectionKind('order', ['ORD-1', 'ORD-2']);
    expect(getSelection().order).toEqual(['ORD-1', 'ORD-2']);
    setSelectionKind('order', []);
    expect(getSelection().order).toBeUndefined();
  });

  it('类型隔离:商品勾选不影响客户勾选', () => {
    setSelectionKind('spu', ['SPU-A']);
    setSelectionKind('customer', ['CUST-1']);
    expect(getSelection().spu).toEqual(['SPU-A']);
    expect(getSelection().customer).toEqual(['CUST-1']);
  });

  it('labels 随勾选上行,清空该类即随删', () => {
    setSelectionKind('spu', ['SPU-A'], { 'SPU-A': '冲锋衣' });
    expect(getSelectionLabels().spu?.['SPU-A']).toBe('冲锋衣');
    setSelectionKind('spu', []);
    expect(getSelectionLabels().spu).toBeUndefined();
  });

  it('toggleKindId 增删切换,超限截断 100', () => {
    toggleKindId('order', 'A');
    toggleKindId('order', 'B');
    expect(getSelection().order).toEqual(['A', 'B']);
    toggleKindId('order', 'A');
    expect(getSelection().order).toEqual(['B']);
    setSelectionKind(
      'order',
      Array.from({ length: 120 }, (_, i) => `O${i}`),
    );
    expect(getSelection().order!.length).toBe(100);
  });

  it('subscribe 即时广播,退订后不再收', () => {
    const seen: unknown[] = [];
    const off = subscribe((s) => seen.push(s));
    setSelectionKind('customer', ['C1']);
    expect(seen.length).toBeGreaterThanOrEqual(2); // 订阅即推一次 + 变更一次
    off();
    setSelectionKind('customer', ['C2']);
    const after = seen.length;
    setSelectionKind('customer', ['C3']);
    expect(seen.length).toBe(after);
  });

  it('新契约不再写 localStorage(勾选是内存态)', () => {
    setSelectionKind('spu', ['SPU-A']);
    toggleKindId('order', 'O1');
    expect(localStorage.getItem('merchant-admin.selection')).toBeNull();
  });

  it('clearSelection 清全部并广播', () => {
    const fn = vi.fn();
    subscribe(fn);
    setSelectionKind('spu', ['S1']);
    clearSelection();
    expect(getSelection()).toEqual({});
    expect(fn).toHaveBeenCalled();
  });
});
