import { type MenuNode, api } from '@/lib/api';
import { useState } from 'react';
import { Button, Input, Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from 'ui';

/** Radix SelectItem 禁空串:「作为顶级」(parentId='')的哨兵值。 */
const ROOT = '__root__';

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
        <Input
          className="h-auto w-36 rounded-lg border-zinc-300 px-3 py-2 text-xs shadow-none focus-visible:ring-0"
          placeholder="名称"
          value={form.name}
          onChange={(e) => setForm({ ...form, name: e.target.value })}
        />
        <Select value={form.menuType} onValueChange={(v) => setForm({ ...form, menuType: v })}>
          <SelectTrigger aria-label="菜单类型" className="h-auto rounded-lg border-zinc-300 px-3 py-2 text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="directory">目录</SelectItem>
            <SelectItem value="menu">菜单</SelectItem>
            <SelectItem value="button">按钮</SelectItem>
          </SelectContent>
        </Select>
        {form.menuType === 'button' && (
          <Input
            className="h-auto w-40 rounded-lg border-zinc-300 px-3 py-2 text-xs shadow-none focus-visible:ring-0"
            placeholder="权限点 perms:x:y"
            value={form.permCode}
            onChange={(e) => setForm({ ...form, permCode: e.target.value })}
          />
        )}
        {form.menuType !== 'directory' && (
          <Input
            className="h-auto w-32 rounded-lg border-zinc-300 px-3 py-2 text-xs shadow-none focus-visible:ring-0"
            placeholder="路由 /xxx"
            value={form.route}
            onChange={(e) => setForm({ ...form, route: e.target.value })}
          />
        )}
        <Select
          value={form.parentId || ROOT}
          onValueChange={(v) => setForm({ ...form, parentId: v === ROOT ? '' : v })}
        >
          <SelectTrigger aria-label="父级" className="h-auto rounded-lg border-zinc-300 px-3 py-2 text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ROOT}>作为顶级</SelectItem>
            {menus.map((d) => (
              <SelectItem key={d.id} value={d.id}>
                {d.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Button size="sm" disabled={!form.name} onClick={() => void create()}>
          新增
        </Button>
      </div>
    </div>
  );
}
