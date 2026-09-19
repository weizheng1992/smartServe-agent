// 菜单树 → TreeTable 行展开纯逻辑(独立模块便于单测)。
import type { MenuNode } from '@/lib/api';

export interface MenuTreeRow {
  node: MenuNode;
  depth: number;
  hasChildren: boolean;
}

/** 深度优先平铺;collapsed 集合中的节点保留自身行但不再下钻。 */
export function flattenMenuTree(nodes: MenuNode[], collapsed: Set<string>, depth = 0): MenuTreeRow[] {
  const rows: MenuTreeRow[] = [];
  for (const n of nodes) {
    const children = n.children || [];
    rows.push({ node: n, depth, hasChildren: children.length > 0 });
    if (children.length > 0 && !collapsed.has(n.id)) {
      rows.push(...flattenMenuTree(children, collapsed, depth + 1));
    }
  }
  return rows;
}

/** 折叠/展开一个节点,返回新集合(受控组件安全)。 */
export function toggleCollapsed(id: string, collapsed: Set<string>): Set<string> {
  const next = new Set(collapsed);
  if (next.has(id)) next.delete(id);
  else next.add(id);
  return next;
}
