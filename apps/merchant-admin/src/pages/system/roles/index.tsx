import { useCallback, useEffect, useState } from 'react';
import { Button } from 'ui';
import { api, authHeaders, hasBossSession, type MenuNode } from '@/lib/api';

// 角色管理(13 号;0013 完整版):角色列表 + 菜单/按钮勾选树分配(新建与
// 再分配共用一棵树,保存即生效 —— 按钮权限点由 role_menus 动态派生)。

interface RoleRow {
  role: string;
  menuCount: number;
  staffCount: number;
  builtin: boolean;
}

function collectIds(n: MenuNode): string[] {
  return [n.id, ...(n.children || []).flatMap(collectIds)];
}

function toggleNode(n: MenuNode, on: boolean, sel: Set<string>): Set<string> {
  const next = new Set(sel);
  for (const id of collectIds(n)) {
    if (on) next.add(id);
    else next.delete(id);
  }
  return next;
}

/** 目录/菜单/按钮三级勾选树:勾父带子,子可单独增减(按钮=接口权限点)。 */
function PermTree({ nodes, selected, onChange }: { nodes: MenuNode[]; selected: Set<string>; onChange: (s: Set<string>) => void }) {
  const render = (n: MenuNode, depth: number) => (
    <div key={n.id}>
      <label className={`flex cursor-pointer items-center gap-2 rounded px-1 py-0.5 hover:bg-zinc-50 ${n.menuType === 'button' ? 'text-xs text-zinc-500' : 'text-[13px]'}`}>
        <input
          type="checkbox"
          className="accent-zinc-900"
          checked={selected.has(n.id)}
          onChange={(e) => onChange(toggleNode(n, e.target.checked, selected))}
        />
        <span>{n.name}</span>
        {n.menuType === 'button' && n.permCode && (
          <code className="rounded bg-zinc-100 px-1 text-[10px] text-zinc-500">{n.permCode}</code>
        )}
      </label>
      {(n.children || []).length > 0 && (
        <div style={{ paddingLeft: 16 }}>{(n.children || []).map((c) => render(c, depth + 1))}</div>
      )}
    </div>
  );
  return <div className="max-h-72 overflow-y-auto rounded-lg border border-zinc-200 p-2">{nodes.map((n) => render(n, 0))}</div>;
}

export default function RolesPage() {
  const [roles, setRoles] = useState<RoleRow[]>([]);
  const [msg, setMsg] = useState('');
  const [tree, setTree] = useState<MenuNode[]>([]);
  const [newRole, setNewRole] = useState('');
  const [newSel, setNewSel] = useState<Set<string>>(new Set(['m-analytics']));
  const [editing, setEditing] = useState<{ role: string; sel: Set<string> } | null>(null);

  const load = useCallback(async () => {
    setRoles((await api.roles.list()).roles || []);
    setTree((await api.menus()).menus || []);
  }, []);
  useEffect(() => { void load(); }, [load]);

  const boss = hasBossSession();

  async function createRole() {
    const body = await api.roles.create(newRole, [...newSel]);
    setMsg(body.success ? `✓ 角色「${body.role}」已建(${body.menuCount} 菜单)` : `失败:${body.message}`);
    if (body.success) { setNewRole(''); setNewSel(new Set()); void load(); }
  }

  async function openAssign(role: string) {
    const detail = await api.roles.menusOf(role);
    setEditing({ role, sel: new Set(detail.menuIds) });
    setMsg('');
  }

  async function saveAssign() {
    if (!editing) return;
    const body = await api.roles.saveMenus(editing.role, [...editing.sel]);
    setMsg(body.success ? `✓ 角色「${editing.role}」权限已更新,保存即生效` : `失败:${body.message}`);
    if (body.success) { setEditing(null); void load(); }
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

      {editing && (
        <div className="rounded-xl border border-zinc-200 bg-white p-4">
          <div className="text-sm font-medium">分配权限 · {editing.role}</div>
          <div className="mt-1 text-[11px] text-zinc-400">
            勾选菜单决定侧边栏可见性;勾选按钮(权限点)决定接口动作,保存即生效。老板角色的系统菜单由服务端强制回补。
          </div>
          <div className="mt-3">
            <PermTree nodes={tree} selected={editing.sel} onChange={(sel) => setEditing({ ...editing, sel })} />
          </div>
          <div className="mt-3 flex items-center gap-2">
            <Button size="sm" disabled={editing.sel.size === 0} onClick={() => void saveAssign()}>保存分配</Button>
            <Button size="sm" variant="ghost" onClick={() => setEditing(null)}>取消</Button>
            {msg && <span className="text-[11px] text-zinc-400">{msg}</span>}
          </div>
        </div>
      )}

      <div className="rounded-xl border border-zinc-200 bg-white p-4">
        <div className="text-sm font-medium">新建自定义角色</div>
        <div className="mt-1 text-[11px] text-zinc-400">
          指标权限:默认沿用运营口径;在「菜单管理」给数据菜单挂 `metric:指标名` 按钮(如 metric:gmv)并勾给角色,即可自定义可见指标。
        </div>
        <div className="mt-3 flex flex-wrap items-start gap-3 text-xs">
          <div className="space-y-2">
            <input className="w-44 rounded-lg border border-zinc-300 px-3 py-2" placeholder="角色标识(如 custom_ops)" value={newRole} onChange={(e) => setNewRole(e.target.value)} />
            <div>
              <Button size="sm" disabled={!newRole || newSel.size === 0} onClick={() => void createRole()}>创建</Button>
            </div>
          </div>
          <div className="min-w-[240px] flex-1">
            <PermTree nodes={tree} selected={newSel} onChange={setNewSel} />
          </div>
        </div>
        <div className="mt-2 text-[11px] text-zinc-400">创建后到「员工管理」给员工分派该角色;员工在登录页以邮箱 + 种子密码(agent-all-dev)登录。</div>
      </div>
    </div>
  );
}
