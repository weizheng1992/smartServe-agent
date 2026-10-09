import {
  DenseTable,
  DenseTableBody,
  DenseTableCell,
  DenseTableHead,
  DenseTableHeader,
  DenseTableRow,
} from '@/components/dense-table';
import { type MenuNode, api } from '@/lib/api';
import { Fragment, useState } from 'react';
import { Button } from 'ui';
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
      <DenseTable>
        <DenseTableHeader>
          <DenseTableRow className="border-b border-zinc-100 hover:bg-transparent">
            <DenseTableHead>名称</DenseTableHead>
            <DenseTableHead>类型</DenseTableHead>
            <DenseTableHead>路由 / 权限点</DenseTableHead>
            <DenseTableHead className="text-right">操作</DenseTableHead>
          </DenseTableRow>
        </DenseTableHeader>
        <DenseTableBody>
          {rows.map(({ node, depth, hasChildren }) => (
            <Fragment key={node.id}>
              <DenseTableRow className="hover:bg-zinc-50/60">
                <DenseTableCell style={{ paddingLeft: 16 + depth * 20 }}>
                  {hasChildren ? (
                    <Button
                      type="button"
                      variant="ghost"
                      className="mr-1.5 inline-block h-auto w-4 cursor-pointer select-none p-0 text-xs font-normal text-zinc-400 hover:bg-transparent"
                      onClick={() => setCollapsed(toggleCollapsed(node.id, collapsed))}
                      aria-label={collapsed.has(node.id) ? `展开 ${node.name}` : `收起 ${node.name}`}
                    >
                      {collapsed.has(node.id) ? '▸' : '▾'}
                    </Button>
                  ) : (
                    <span className="mr-1.5 inline-block w-4 text-center text-zinc-300">·</span>
                  )}
                  <span className={node.menuType === 'directory' ? 'font-semibold' : ''}>{node.name}</span>
                </DenseTableCell>
                <DenseTableCell className="text-zinc-500">{TYPE_BADGE[node.menuType] || node.menuType}</DenseTableCell>
                <DenseTableCell className="text-zinc-500">
                  {node.permCode ? (
                    <code className="rounded bg-zinc-100 px-1 text-[11px]">{node.permCode}</code>
                  ) : (
                    node.route || '—'
                  )}
                </DenseTableCell>
                <DenseTableCell className="text-right">
                  <Button size="sm" variant="ghost" className="text-rose-600" onClick={() => void remove(node)}>
                    删除
                  </Button>
                </DenseTableCell>
              </DenseTableRow>
            </Fragment>
          ))}
        </DenseTableBody>
      </DenseTable>
    </div>
  );
}
