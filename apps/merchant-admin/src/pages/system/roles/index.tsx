import { useCallback, useEffect, useState } from 'react';
import { Button } from 'ui';
import { api, type MenuNode } from '@/lib/api';
import { RoleAssignPanel } from './components/role-assign-panel';
import { RoleCreateForm } from './components/role-create-form';

// 角色管理(0014 后无「内置」概念):三档种子只是预置配置,与自定义角色一样
// 可重新分配菜单+按钮;仅老板角色保留系统菜单防锁死护栏(服务端强制回补)。
// 页面只做编排:勾选树/分配面板/新建表单拆在同目录 components/ 下。
interface RoleRow {
  role: string;
  menuCount: number;
  staffCount: number;
}

export default function RolesPage() {
  const [roles, setRoles] = useState<RoleRow[]>([]);
  const [tree, setTree] = useState<MenuNode[]>([]);
  const [msg, setMsg] = useState('');
  const [assigning, setAssigning] = useState<string | null>(null);
  const [canAssign, setCanAssign] = useState(false);

  const load = useCallback(async () => {
    setRoles((await api.roles.list()).roles || []);
    const m = await api.menus();
    setTree(m.menus || []);
    // 分配权限点(老板/管理员角色自带 role:assign;也可经菜单管理勾给其他角色)
    setCanAssign((m.perms || []).includes('role:assign'));
  }, []);
  useEffect(() => { void load(); }, [load]);

  const boss = canAssign;

  async function openAssign(role: string) {
    setMsg('');
    setAssigning(role);
  }

  return (
    <div className="mx-auto max-w-4xl space-y-4">
      <div className="overflow-hidden rounded-xl border border-zinc-200 bg-white">
        <div className="flex items-center justify-between border-b border-zinc-100 px-4 py-3 text-sm font-medium">
          <span>角色列表</span>
          {!boss && <span className="text-[11px] text-zinc-400">需 role:assign 权限点(老板/管理员)</span>}
        </div>
        <table className="w-full text-[13px]">
          <thead>
            <tr className="border-b border-zinc-100 text-left text-zinc-400">
              <th className="px-4 py-2 font-medium">角色</th>
              <th className="px-4 py-2 font-medium">菜单/权限点数</th>
              <th className="px-4 py-2 font-medium">员工数</th>
              <th className="px-4 py-2 font-medium">操作</th>
            </tr>
          </thead>
          <tbody>
            {roles.map((r) => (
              <tr key={r.role} className="border-b border-zinc-50">
                <td className="px-4 py-2">{r.role}</td>
                <td className="px-4 py-2">{r.menuCount}</td>
                <td className="px-4 py-2">{r.staffCount}</td>
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
