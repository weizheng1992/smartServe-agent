import { type MenuNode, api } from '@/lib/api';
import { useState } from 'react';
import { Button } from 'ui';

interface Props {
  menus: MenuNode[];
  onMsg: (m: string) => void;
  onCreated: () => void;
}

const EMPTY = { name: '', menuType: 'menu', route: '', parentId: '', permCode: '' };

/** 新增菜单/按钮:按钮型需权限点(即角色管理页可勾选的接口权限)。 */
export function MenuCreateForm({ menus, onMsg, onCreated }: Props) {
  const [form, setForm] = useState(EMPTY);

  async function create() {
    const body = await api.menuAdmin.create({ ...form, sort: 9, parentId: form.parentId || null });
    onMsg(body.success ? `✓ 已新增「${form.name}」` : `失败:${body.message}`);
    if (body.success) {
      setForm(EMPTY);
      onCreated();
    }
  }

  return (
    <div className="rounded-xl border border-zinc-200 bg-white p-4">
      <div className="text-sm font-medium">新增菜单 / 按钮</div>
      <div className="mt-3 flex flex-wrap items-center gap-2 text-xs">
        <input
          className="w-36 rounded-lg border border-zinc-300 px-3 py-2"
          placeholder="名称"
          value={form.name}
          onChange={(e) => setForm({ ...form, name: e.target.value })}
        />
        <select
          className="rounded-lg border border-zinc-300 px-3 py-2"
          value={form.menuType}
          onChange={(e) => setForm({ ...form, menuType: e.target.value })}
        >
          <option value="directory">目录</option>
          <option value="menu">菜单</option>
          <option value="button">按钮</option>
        </select>
        {form.menuType === 'button' && (
          <input
            className="w-40 rounded-lg border border-zinc-300 px-3 py-2"
            placeholder="权限点 perms:x:y"
            value={form.permCode}
            onChange={(e) => setForm({ ...form, permCode: e.target.value })}
          />
        )}
        {form.menuType !== 'directory' && (
          <input
            className="w-32 rounded-lg border border-zinc-300 px-3 py-2"
            placeholder="路由 /xxx"
            value={form.route}
            onChange={(e) => setForm({ ...form, route: e.target.value })}
          />
        )}
        <select
          className="rounded-lg border border-zinc-300 px-3 py-2"
          value={form.parentId}
          onChange={(e) => setForm({ ...form, parentId: e.target.value })}
        >
          <option value="">作为顶级</option>
          {menus.map((d) => (
            <option key={d.id} value={d.id}>
              {d.name}
            </option>
          ))}
        </select>
        <Button size="sm" disabled={!form.name} onClick={() => void create()}>
          新增
        </Button>
      </div>
    </div>
  );
}
