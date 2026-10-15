import { type MenuNode, api } from '@/lib/api';
import { useListPage } from '@/lib/use-list-page';
import { useState } from 'react';
import { Button } from 'ui';
import { MenuCreateDialog } from './components/menu-create-form';
import { MenuTable } from './components/menu-table';

// 菜单管理(13 号 RBAC):树列表 + 新增(弹窗)+ 删叶子;系统菜单服务端护栏。
// 这里登记的按钮权限点(perm_code)即角色管理页可勾选的接口权限。
// 页面只做编排;新增弹窗与树列表拆在同目录 components/ 下。
export default function MenusPage() {
  const { rows: menus, msg, setMsg, reload } = useListPage<MenuNode>(async () => (await api.menus()).menus || []);
  const [creating, setCreating] = useState(false);

  return (
    <div className="mx-auto max-w-5xl space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <div className="text-sm font-medium">菜单管理</div>
          <div className="mt-0.5 text-xs text-zinc-400">目录 / 菜单 / 按钮权限点树;权限点供角色分配</div>
        </div>
        <Button size="sm" onClick={() => setCreating(true)}>
          + 新增菜单
        </Button>
      </div>
      <MenuTable menus={menus} onMsg={setMsg} onChanged={() => void reload()} />
      {creating && (
        <MenuCreateDialog
          menus={menus}
          onMsg={setMsg}
          onClose={() => {
            setCreating(false);
            void reload();
          }}
        />
      )}
      {msg && <div className="text-[11px] text-zinc-400">{msg}</div>}
    </div>
  );
}
