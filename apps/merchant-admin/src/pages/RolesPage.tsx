import { useCallback, useEffect, useState } from 'react';
import { Button } from 'ui';
import { currentStaff } from '@/lib/api';

// 角色管理(13 号):列表 + 新建(选菜单集);分配明细走角色→菜单勾选。
interface RoleRow {
  role: string;
  menuCount: number;
  staffCount: number;
  builtin: boolean;
}

export default function RolesPage() {
  const [roles, setRoles] = useState<RoleRow[]>([]);
  const [msg, setMsg] = useState('');
  const [newRole, setNewRole] = useState('');
  const [picked, setPicked] = useState<string[]>(['m-analytics', 'm-reports']);

  const H = () => ({ 'Content-Type': 'application/json', 'x-tenant-id': 'aurora', 'x-user-id': currentStaff() });
  const load = useCallback(async () => {
    const res = await fetch('/api/admin/analytics/roles', { headers: H() });
    setRoles((await res.json()).roles || []);
  }, []);
  useEffect(() => { void load(); }, [load]);

  async function loadMenuOptions(): Promise<MenuOpt[]> {
    const res = await fetch('/api/admin/analytics/menus', { headers: H() });
    const body = await res.json();
    const out: MenuOpt[] = [];
    const walk = (nodes: MenuNode[], depth: number) =>
      nodes.forEach((n) => {
        if (n.menuType !== 'button') out.push({ id: n.id, name: '　'.repeat(depth) + n.name });
        walk(n.children || [], depth + 1);
      });
    walk(body.menus || [], 0);
    return out;
  }
  const [menuOptions, setMenuOptions] = useState<MenuOpt[]>([]);
  useEffect(() => { void loadMenuOptions().then(setMenuOptions); }, []);

  async function createRole() {
    const res = await fetch('/api/admin/analytics/roles', {
      method: 'POST',
      headers: H(),
      body: JSON.stringify({ role: newRole, menuIds: picked }),
    });
    const body = await res.json();
    setMsg(body.success ? `✓ 角色「${body.role}」已建(${body.menuCount} 菜单)` : `失败:${body.message}`);
    if (body.success) { setNewRole(''); void load(); }
  }

  return (
    <div className="mx-auto max-w-4xl space-y-4">
      <div className="overflow-hidden rounded-xl border border-zinc-200 bg-white">
        <div className="border-b border-zinc-100 px-4 py-3 text-sm font-medium">角色列表</div>
        <table className="w-full text-[13px]">
          <thead>
            <tr className="border-b border-zinc-100 text-left text-zinc-400">
              <th className="px-4 py-2 font-medium">角色</th>
              <th className="px-4 py-2 font-medium">可见菜单数</th>
              <th className="px-4 py-2 font-medium">员工数</th>
              <th className="px-4 py-2 font-medium">类型</th>
            </tr>
          </thead>
          <tbody>
            {roles.map((r) => (
              <tr key={r.role} className="border-b border-zinc-50">
                <td className="px-4 py-2">{r.role}</td>
                <td className="px-4 py-2">{r.menuCount}</td>
                <td className="px-4 py-2">{r.staffCount}</td>
                <td className="px-4 py-2 text-zinc-500">{r.builtin ? '内置' : '自定义'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="rounded-xl border border-zinc-200 bg-white p-4">
        <div className="text-sm font-medium">新建自定义角色</div>
        <div className="mt-3 flex flex-wrap items-center gap-2 text-xs">
          <input className="w-44 rounded-lg border border-zinc-300 px-3 py-2" placeholder="角色标识(如 custom_ops)" value={newRole} onChange={(e) => setNewRole(e.target.value)} />
          <select multiple className="h-20 rounded-lg border border-zinc-300 px-3 py-2" value={picked} onChange={(e) => setPicked([...e.target.selectedOptions].map((o) => o.value))}>
            {menuOptions.map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}
          </select>
          <Button size="sm" disabled={!newRole || picked.length === 0} onClick={() => void createRole()}>创建</Button>
          {msg && <span className="text-[11px] text-zinc-400">{msg}</span>}
        </div>
        <div className="mt-2 text-[11px] text-zinc-400">创建后到「员工管理」给员工分派该角色;指标权限沿用角色三档语义。</div>
      </div>
    </div>
  );
}

interface MenuOpt { id: string; name: string }
interface MenuNode { id: string; name: string; menuType: string; children?: MenuNode[] }
