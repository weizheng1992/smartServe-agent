import { describe, expect, it } from 'vitest';
import { routeAllowed } from './route-guard';

// 服务端菜单树形状(仅测试所需字段;route 为服务端下发,runtime 非空串)
const tree = [
  {
    id: 'd-orders',
    name: '订单',
    menuType: 'directory' as const,
    children: [
      { id: 'm-orders', name: '订单管理', menuType: 'menu' as const, route: '/orders' },
      { id: 'm-spi-logs', name: '接口日志', menuType: 'menu' as const, route: '/spi-logs' },
    ],
  },
  {
    id: 'd-goods',
    name: '商品',
    menuType: 'directory' as const,
    children: [{ id: 'm-products', name: '商品管理', menuType: 'menu' as const, route: '/products' }],
  },
] as unknown as Parameters<typeof routeAllowed>[1];

describe('routeGuard(菜单驱动路由守卫,直敲 URL 封堵)', () => {
  it('菜单树内的路由与子路径放行(详情页 /products/:code 随 /products 放行)', () => {
    expect(routeAllowed('/orders', tree)).toBe(true);
    expect(routeAllowed('/products', tree)).toBe(true);
    expect(routeAllowed('/products/AURORA-SKU-001', tree)).toBe(true);
  });

  it('菜单树外的路径拒绝(直敲 URL /staff 无该菜单 → 无权页)', () => {
    expect(routeAllowed('/staff', tree)).toBe(false);
    expect(routeAllowed('/agent-desk', tree)).toBe(false);
  });

  it('前缀不串门:/orderX 不得借 /orders 放行', () => {
    expect(routeAllowed('/orderx', tree)).toBe(false);
  });

  it('菜单未加载/加载失败(空树)一律拒绝(fail-closed,调用方呈现加载/重试态)', () => {
    expect(routeAllowed('/orders', [])).toBe(false);
  });
});
