import { useCallback, useEffect, useState } from 'react';
import { Button } from 'ui';
import { api, hasBossSession, type MenuNode } from '@/lib/api';
import { RoleAssignPanel } from './components/role-assign-panel';
import { RoleCreateForm } from './components/role-create-form';

// 角色管理(13 号;0013 完整版):角色列表 + 菜单/按钮勾选树分配。
// 页面只做编排:勾选树/分配面板/新建表单拆在同目录 components/ 下。
interface RoleRow {
  role: string;
  menuCount: number;
  staffCount: number;
  builtin: boolean;
}

export default function RolesPage() {
  const [roles, setRoles] = useState<RoleRow[]>([]);
  const [tree, setTree] = useState<MenuNode[]>([]);
  const [msg, setMsg] = useState('');
  const [assigning, setAssigning] = useState<string | null>(null);

  const load = useCallback(async () => {
    setRoles((await api.roles.list()).roles || []);
    setTree((await api.menus()).menus || []);
  }, []);
  useEffect(() => { void load(); }, [load]);

  const boss = hasBossSession();

  async function openAssign(role: string) {
    setMsg('');
    setAssigning(role);
  }

  return (
    <div className="mx-auto max-w-4xl space-y-4">
      <div className="overflow-hidden rounded-xl border border-zinc-200 bg-white">
        <div className="flex items-center justify-between border-b border-zinc-100 px-4 py-3 text-sm font-medium">
          <span>角色列表</span>
          {!boss && <span className="text-[11px] text-zinc-400">仅老板可分配权限</span>}
        </div>
        <table className="w-full text-[13px]">
          <thead>
            <tr className="border-b border-zinc-100 text-left text-zinc-400">
              <th className="px-4 py-2 font-medium">角色</th>
              <th className="px-4 py-2 font-medium">菜单/权限点数</th>
              <th className="px-4 py-2 font-medium">员工数</th>
              <th className="px-4 py-2 font-medium">类型</th>
              <th className="px-4 py-2 font-medium">操作</th>
            </tr>
          </thead>
          <tbody>
            {roles.map((r) => (
              <tr key={r.role} className="border-b border-zinc-50">
                <td className="px-4 py-2">{r.role}</td>
                <td className="px-4 py-2">{r.menuCount}</td>
                <td className="px-4 py-2">{r.staffCount}</td>
                <td className="px-4 py-2 text-zinc-500">{r.builtin ? '内置' : '自定义'}</td>
                <td className="px-4 py-2">
                  {boss && (
                    <Button size="sm" variant="ghost" onClick={() => void openAssign(r.role)}>
                      {r.role === 'finance_owner' ? '查看/分配(系统菜单强制保留)' : '分配权限'}
                    </Button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {assigning && (
        <RoleAssignPanel
          role={assigning}
          tree={tree}
          onSaved={setMsg}
          onCancel={() => { setAssigning(null); void load(); }}
        />
      )}

      <RoleCreateForm tree={tree} onMsg={setMsg} onCreated={() => void load()} />
      {msg && <div className="text-[11px] text-zinc-400">{msg}</div>}
    </div>
  );
}
