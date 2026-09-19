import { describe, expect, it } from 'vitest';
import type { MenuNode } from './api';
import { collectIds, toggleNode } from './perm-tree';

const tree: MenuNode[] = [
  {
    id: 'd1', name: '商品', menuType: 'directory', route: null, permCode: null,
    children: [
      {
        id: 'm1', name: '商品列表', menuType: 'menu', route: '/products', permCode: null,
        children: [
          { id: 'b1', name: '商品编辑', menuType: 'button', route: null, permCode: 'prod:edit', children: [] },
        ],
      },
      { id: 'm2', name: 'SKU 库存', menuType: 'menu', route: '/skus', permCode: null, children: [] },
    ],
  },
  { id: 'm9', name: '我的报告', menuType: 'menu', route: '/reports', permCode: null, children: [] },
];

describe('collectIds', () => {
  it('收集节点及全部后代', () => {
    expect(collectIds(tree[0])).toEqual(['d1', 'm1', 'b1', 'm2']);
    expect(collectIds(tree[1])).toEqual(['m9']);
  });
});

describe('toggleNode', () => {
  it('勾选父节点 = 整棵子树置位,不影响兄弟子树', () => {
    const next = toggleNode(tree[0], true, new Set(['m9']));
    expect([...next].sort()).toEqual(['b1', 'd1', 'm1', 'm2', 'm9']);
  });

  it('去勾父节点 = 整棵子树清除,勾选外的保持', () => {
    const full = new Set(['d1', 'm1', 'b1', 'm2', 'm9']);
    const next = toggleNode(tree[0], false, full);
    expect([...next]).toEqual(['m9']);
  });

  it('子节点可单独回收,不影响父与兄弟', () => {
    const full = new Set(['d1', 'm1', 'b1', 'm2']);
    const next = toggleNode(tree[0].children![0].children![0], false, full);
    expect([...next].sort()).toEqual(['d1', 'm1', 'm2']);
  });

  it('返回新集合,不变更入参(受控组件安全)', () => {
    const prev = new Set(['d1']);
    const next = toggleNode(tree[0], true, prev);
    expect(next).not.toBe(prev);
    expect([...prev]).toEqual(['d1']);
  });
});
