import { useCallback, useEffect, useState } from 'react';
import { Button } from 'ui';
import { authHeaders, type MenuNode } from '@/lib/api';

// 菜单管理(13 号 RBAC):树列表 + 新增 + 启停 + 删叶子;系统菜单服务端护栏。
// 这里登记的按钮权限点(perm_code)即角色管理页可勾选的接口权限。
export default function MenusPage() {
  const [menus, setMenus] = useState<MenuNode[]>([]);
  const [msg, setMsg] = useState('');
  const [form, setForm] = useState({ name: '', menuType: 'menu', route: '', parentId: '', permCode: '' });

  const H = authHeaders;

  const load = useCallback(async () => {
    const res = await fetch('/api/admin/analytics/menus', { headers: H() });
    setMenus((await res.json()).menus || []);
  }, []);
  useEffect(() => { void load(); }, [load]);

  const flatten = (nodes: MenuNode[], parentName = ''): Array<MenuNode & { path: string }> =>
    nodes.flatMap((n) => [
      { ...n, path: parentName ? `${parentName} / ${n.name}` : n.name },
      ...flatten(n.children || [], parentName ? `${parentName} / ${n.name}` : n.name),
    ]);

  async function create() {
    const res = await fetch('/api/admin/analytics/menus', {
      method: 'POST',
      headers: H(),
      body: JSON.stringify({ ...form, sort: 9, parentId: form.parentId || null }),
    });
    const body = await res.json();
    setMsg(body.success ? `✓ 已新增「${form.name}」` : `失败:${body.message}`);
    if (body.success) { setForm({ name: '', menuType: 'menu', route: '', parentId: '', permCode: '' }); void load(); }
  }

  async function toggleStatus(n: MenuNode) {
    const res = await fetch(`/api/admin/analytics/menus/${n.id}`, {
      method: 'PATCH',
      headers: H(),
      body: JSON.stringify({ status: 'enabled' }),
    });
    const body = await res.json();
    setMsg(body.success ? `✓ 「${n.name}」已启用` : `失败:${body.message}`);
    void load();
  }

  async function remove(n: MenuNode) {
    const res = await fetch(`/api/admin/analytics/menus/${n.id}`, { method: 'DELETE', headers: H() });
    const body = await res.json();
    setMsg(body.success ? `✓ 已删除「${n.name}」` : `失败:${body.message}`);
    void load();
  }

  return (
    <div className="mx-auto max-w-5xl space-y-4">
      <div className="rounded-xl border border-zinc-200 bg-white p-4">
        <div className="text-sm font-medium">新增菜单 / 按钮</div>
        <div className="mt-3 flex flex-wrap items-center gap-2 text-xs">
          <input className="w-36 rounded-lg border border-zinc-300 px-3 py-2" placeholder="名称" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
          <select className="rounded-lg border border-zinc-300 px-3 py-2" value={form.menuType} onChange={(e) => setForm({ ...form, menuType: e.target.value })}>
            <option value="directory">目录</option>
            <option value="menu">菜单</option>
            <option value="button">按钮</option>
          </select>
          {form.menuType === 'button' && (
            <input className="w-40 rounded-lg border border-zinc-300 px-3 py-2" placeholder="权限点 perms:x:y" value={form.permCode} onChange={(e) => setForm({ ...form, permCode: e.target.value })} />
          )}
          {form.menuType !== 'directory' && (
            <input className="w-32 rounded-lg border border-zinc-300 px-3 py-2" placeholder="路由 /xxx" value={form.route} onChange={(e) => setForm({ ...form, route: e.target.value })} />
          )}
          <select className="rounded-lg border border-zinc-300 px-3 py-2" value={form.parentId} onChange={(e) => setForm({ ...form, parentId: e.target.value })}>
            <option value="">作为顶级</option>
            {menus.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
          </select>
          <Button size="sm" disabled={!form.name} onClick={() => void create()}>新增</Button>
          {msg && <span className="text-[11px] text-zinc-400">{msg}</span>}
        </div>
      </div>

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
    </div>
  );
}
