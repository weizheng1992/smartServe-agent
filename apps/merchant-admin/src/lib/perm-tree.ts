// 权限勾选树纯逻辑(角色管理页用;独立模块便于单测)。
import type { MenuNode } from '@/lib/api';

/** 收集节点及其全部后代 id(勾父带子)。 */
export function collectIds(n: MenuNode): string[] {
  return [n.id, ...(n.children || []).flatMap(collectIds)];
}

/** 勾/去勾一个节点:整棵子树一并置位/清除;子节点可单独增减。 */
export function toggleNode(n: MenuNode, on: boolean, sel: Set<string>): Set<string> {
  const next = new Set(sel);
  for (const id of collectIds(n)) {
    if (on) next.add(id);
    else next.delete(id);
  }
  return next;
}
