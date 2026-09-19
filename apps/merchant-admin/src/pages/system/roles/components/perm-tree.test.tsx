import '@testing-library/jest-dom/vitest';
import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import type { MenuNode } from '@/lib/api';
import { PermTree } from './perm-tree';

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
    ],
  },
];

const findBox = (name: RegExp) => screen.getByRole('checkbox', { name }) as HTMLInputElement;

describe('PermTree', () => {
  it('渲染三级节点,按钮节点带权限点徽标', () => {
    render(<PermTree nodes={tree} selected={new Set()} onChange={() => {}} />);
    expect(findBox(/商品$/)).toBeInTheDocument();
    expect(findBox(/商品列表/)).toBeInTheDocument();
    expect(findBox(/prod:edit/)).toBeInTheDocument();
    expect(screen.getByText('prod:edit')).toBeInTheDocument();
  });

  it('勾选父目录 → 整棵子树随 onChange 上行', () => {
    const onChange = vi.fn();
    render(<PermTree nodes={tree} selected={new Set()} onChange={onChange} />);
    fireEvent.click(findBox(/商品$/));
    const sel = onChange.mock.calls[0][0] as Set<string>;
    expect([...sel].sort()).toEqual(['b1', 'd1', 'm1']);
  });

  it('受控勾选态下取消按钮权限点 → 仅该点从集合移除', () => {
    const onChange = vi.fn();
    render(<PermTree nodes={tree} selected={new Set(['d1', 'm1', 'b1'])} onChange={onChange} />);
    expect(findBox(/prod:edit/).checked).toBe(true);
    fireEvent.click(findBox(/prod:edit/));
    const sel = onChange.mock.calls[0][0] as Set<string>;
    expect(sel.has('b1')).toBe(false);
    expect(sel.has('d1') && sel.has('m1')).toBe(true);
  });
});
