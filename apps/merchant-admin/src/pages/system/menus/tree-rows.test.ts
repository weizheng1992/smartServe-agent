import { describe, expect, it } from 'vitest';
import type { MenuNode } from '@/lib/api';
import { flattenMenuTree, toggleCollapsed } from './tree-rows';

const tree: MenuNode[] = [
  {
    id: 'd1', name: '商品', menuType: 'directory', route: null, permCode: null,
    children: [
      { id: 'm1', name: '商品列表', menuType: 'menu', route: '/products', permCode: null, children: [] },
      {
        id: 'm2', name: 'SKU 库存', menuType: 'menu', route: '/skus', permCode: null,
        children: [
          { id: 'b1', name: '按钮', menuType: 'button', route: null, permCode: 'sku:x', children: [] },
        ],
      },
    ],
  },
];

describe('flattenMenuTree', () => {
  it('全展开:深度优先平铺并带层级', () => {
    const rows = flattenMenuTree(tree, new Set());
    expect(rows.map((r) => [r.node.id, r.depth])).toEqual([
      ['d1', 0], ['m1', 1], ['m2', 1], ['b1', 2],
    ]);
    expect(rows[0].hasChildren).toBe(true);
    expect(rows[1].hasChildren).toBe(false);
  });

  it('折叠目录:保留自身行但不下钻', () => {
    const rows = flattenMenuTree(tree, new Set(['d1']));
    expect(rows.map((r) => r.node.id)).toEqual(['d1']);
    expect(rows[0].hasChildren).toBe(true);
  });

  it('折叠中间节点:孙级随子级一起隐藏', () => {
    const rows = flattenMenuTree(tree, new Set(['m2']));
    expect(rows.map((r) => r.node.id)).toEqual(['d1', 'm1', 'm2']);
  });
});

describe('toggleCollapsed', () => {
  it('折叠/展开互斥,返回新集合', () => {
    const collapsed = toggleCollapsed('d1', new Set());
    expect(collapsed.has('d1')).toBe(true);
    const expanded = toggleCollapsed('d1', collapsed);
    expect(expanded.has('d1')).toBe(false);
    expect(collapsed.has('d1')).toBe(true); // 入参不变
  });
});
