import { useCallback, useEffect, useState } from 'react';
import { api, type MenuNode } from '@/lib/api';
import { MenuCreateForm } from './components/menu-create-form';
import { MenuTable } from './components/menu-table';

// 菜单管理(13 号 RBAC):树列表 + 新增 + 删叶子;系统菜单服务端护栏。
// 这里登记的按钮权限点(perm_code)即角色管理页可勾选的接口权限。
// 页面只做编排;新增表单与树列表拆在同目录 components/ 下。
export default function MenusPage() {
  const [menus, setMenus] = useState<MenuNode[]>([]);
  const [msg, setMsg] = useState('');

  const load = useCallback(async () => {
    setMenus((await api.menus()).menus || []);
  }, []);
  useEffect(() => { void load(); }, [load]);

  return (
    <div className="mx-auto max-w-5xl space-y-4">
      <MenuCreateForm menus={menus} onMsg={setMsg} onCreated={() => void load()} />
      <MenuTable menus={menus} onMsg={setMsg} onChanged={() => void load()} />
      {msg && <div className="text-[11px] text-zinc-400">{msg}</div>}
    </div>
  );
}
