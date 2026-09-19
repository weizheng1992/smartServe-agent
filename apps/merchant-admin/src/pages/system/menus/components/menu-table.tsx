import { Fragment, useState } from 'react';
import { Button } from 'ui';
import { api, type MenuNode } from '@/lib/api';
import { flattenMenuTree, toggleCollapsed } from '../tree-rows';

interface Props {
  menus: MenuNode[];
  onMsg: (m: string) => void;
  onChanged: () => void;
}

const TYPE_BADGE: Record<string, string> = {
  directory: '📁 目录',
  menu: '📄 菜单',
  button: '🔘 按钮',
};

/** 菜单 TreeTable:目录可展开/收起,按钮节点带权限点;删除仅叶子(服务端护栏)。 */
export function MenuTable({ menus, onMsg, onChanged }: Props) {
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const rows = flattenMenuTree(menus, collapsed);

  async function remove(n: MenuNode) {
    const body = await api.menuAdmin.remove(n.id);
    onMsg(body.success ? `✓ 已删除「${n.name}」` : `失败:${body.message}`);
    if (body.success) onChanged();
  }

  return (
    <div className="overflow-hidden rounded-xl border border-zinc-200 bg-white">
      <table className="w-full text-[13px]">
        <thead>
          <tr className="border-b border-zinc-100 text-left text-zinc-400">
            <th className="px-4 py-2 font-medium">名称</th>
            <th className="px-4 py-2 font-medium">类型</th>
            <th className="px-4 py-2 font-medium">路由 / 权限点</th>
            <th className="px-4 py-2 font-medium text-right">操作</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(({ node, depth, hasChildren }) => (
            <Fragment key={node.id}>
              <tr className="border-b border-zinc-50 hover:bg-zinc-50/60">
                <td className="px-4 py-2" style={{ paddingLeft: 16 + depth * 20 }}>
                  {hasChildren ? (
                    <button
                      type="button"
                      className="mr-1.5 inline-block w-4 cursor-pointer select-none text-zinc-400"
                      onClick={() => setCollapsed(toggleCollapsed(node.id, collapsed))}
                      aria-label={collapsed.has(node.id) ? `展开 ${node.name}` : `收起 ${node.name}`}
                    >
                      {collapsed.has(node.id) ? '▸' : '▾'}
                    </button>
                  ) : (
                    <span className="mr-1.5 inline-block w-4 text-center text-zinc-300">·</span>
                  )}
                  <span className={node.menuType === 'directory' ? 'font-semibold' : ''}>{node.name}</span>
                </td>
                <td className="px-4 py-2 text-zinc-500">{TYPE_BADGE[node.menuType] || node.menuType}</td>
                <td className="px-4 py-2 text-zinc-500">
                  {node.permCode ? <code className="rounded bg-zinc-100 px-1 text-[11px]">{node.permCode}</code> : node.route || '—'}
                </td>
                <td className="px-4 py-2 text-right">
                  <Button size="sm" variant="ghost" className="text-rose-600" onClick={() => void remove(node)}>删除</Button>
                </td>
              </tr>
            </Fragment>
          ))}
        </tbody>
      </table>
    </div>
  );
}
