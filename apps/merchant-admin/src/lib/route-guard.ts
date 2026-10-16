import type { MenuNode } from './api';

/** 菜单树拍平为可路由条目(directory 下的 menu;route 为服务端下发)。 */
export function flattenMenus(nodes: MenuNode[]): Array<MenuNode & { top: string }> {
  return nodes.flatMap((n) => [
    ...(n.menuType === 'menu' ? [{ ...n, top: n.name }] : []),
    ...flattenMenus(n.children || []),
  ]);
}

/**
 * 菜单驱动路由守卫(2026-10-13 夜评:路由静态全注册,直敲 URL 可入无权页;
 * 服务端 is_manager 403 只兜住数据,页面骨架仍整页渲染)。
 *
 * 纪律不变(merchant-admin.md §2.3):RBAC 前端只做可见性,真源是服务端下发的
 * 菜单树 —— 本守卫只回答「该路径是否在当前员工菜单树内」,不复制权限表。
 * 空树(菜单未加载/加载失败)一律 false,调用方呈现加载/重试态(fail-closed)。
 * 信任边界如实(2026-10-15 安全审计 #3):本守卫拦截页面骨架;读数据面的服务端
 * permCode 闸尚未覆盖(直打网关由身份/租户闸兜底),严禁把本守卫当数据闸陈述。
 */
export function routeAllowed(pathname: string, nodes: MenuNode[]): boolean {
  if (!nodes.length) return false;
  return flattenMenus(nodes).some((m) => Boolean(m.route) && pathname.startsWith(m.route || '###'));
}
