import { Button } from 'ui';
import { api, type MenuNode } from '@/lib/api';

interface Props {
  menus: MenuNode[];
  onMsg: (m: string) => void;
  onChanged: () => void;
}

const flatten = (nodes: MenuNode[], parentName = ''): Array<MenuNode & { path: string }> =>
  nodes.flatMap((n) => [
    { ...n, path: parentName ? `${parentName} / ${n.name}` : n.name },
    ...flatten(n.children || [], parentName ? `${parentName} / ${n.name}` : n.name),
  ]);

/** 菜单树列表(平铺展示 + 删叶子;系统菜单护栏在服务端)。 */
export function MenuTable({ menus, onMsg, onChanged }: Props) {
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
            <th className="px-4 py-2 font-medium">路由/权限点</th>
            <th className="px-4 py-2 font-medium">操作</th>
          </tr>
        </thead>
        <tbody>
          {flatten(menus).map((n) => (
            <tr key={n.id} className="border-b border-zinc-50">
              <td className="px-4 py-2">{n.path}</td>
              <td className="px-4 py-2 text-zinc-500">{n.menuType}</td>
              <td className="px-4 py-2 text-zinc-500">{n.route || n.permCode || '—'}</td>
              <td className="px-4 py-2">
                <Button size="sm" variant="ghost" onClick={() => void remove(n)}>删除</Button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
