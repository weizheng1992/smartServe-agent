import { FormDialogShell } from '@/components/form-dialog-shell';
import { OptionalSelect } from '@/components/optional-select';
import { type MenuNode, api, errMsgOf } from '@/lib/api';
import { useState } from 'react';
import { Input, Label, Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from 'ui';

interface Props {
  menus: MenuNode[];
  onMsg: (m: string) => void;
  onClose: () => void;
}

const EMPTY = { name: '', menuType: 'menu', route: '', parentId: '', permCode: '' };

/** 新增菜单/按钮弹窗:按钮型需权限点(即角色管理页可勾选的接口权限);
 * 父级空值走 OptionalSelect(onChange 直收 '',提交前映射 null)。 */
export function MenuCreateDialog({ menus, onMsg, onClose }: Props) {
  const [form, setForm] = useState(EMPTY);

  return (
    <FormDialogShell
      title="新增菜单 / 按钮"
      subtitle={<>这里登记的按钮权限点(perm_code)即角色管理页可勾选的接口权限;系统菜单由服务端护栏保护。</>}
      submitLabel="新增"
      submitDisabled={!form.name}
      onClose={onClose}
      onSubmit={async () => {
        const body = await api.menuAdmin.create({ ...form, sort: 9, parentId: form.parentId || null });
        if (!body.success) return errMsgOf(body);
        onMsg(`✓ 已新增「${form.name}」`);
        return null;
      }}
    >
      <div>
        <Label htmlFor="menu-name" className="mb-1.5 block text-zinc-700">
          名称
        </Label>
        <Input
          id="menu-name"
          className="h-auto w-full rounded-lg border-zinc-300 px-3 py-2 shadow-none focus-visible:ring-0"
          placeholder="菜单名称"
          value={form.name}
          onChange={(e) => setForm({ ...form, name: e.target.value })}
        />
      </div>
      <div>
        <Label htmlFor="menu-type" className="mb-1.5 block text-zinc-700">
          类型
        </Label>
        <Select value={form.menuType} onValueChange={(v) => setForm({ ...form, menuType: v })}>
          <SelectTrigger
            id="menu-type"
            aria-label="菜单类型"
            className="h-auto w-full rounded-lg border-zinc-300 px-3 py-2"
          >
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="directory">目录</SelectItem>
            <SelectItem value="menu">菜单</SelectItem>
            <SelectItem value="button">按钮</SelectItem>
          </SelectContent>
        </Select>
      </div>
      {form.menuType === 'button' && (
        <div>
          <Label htmlFor="menu-perm" className="mb-1.5 block text-zinc-700">
            权限点
          </Label>
          <Input
            id="menu-perm"
            className="h-auto w-full rounded-lg border-zinc-300 px-3 py-2 shadow-none focus-visible:ring-0"
            placeholder="perms:x:y"
            value={form.permCode}
            onChange={(e) => setForm({ ...form, permCode: e.target.value })}
          />
        </div>
      )}
      {form.menuType !== 'directory' && (
        <div>
          <Label htmlFor="menu-route" className="mb-1.5 block text-zinc-700">
            路由
          </Label>
          <Input
            id="menu-route"
            className="h-auto w-full rounded-lg border-zinc-300 px-3 py-2 shadow-none focus-visible:ring-0"
            placeholder="/xxx"
            value={form.route}
            onChange={(e) => setForm({ ...form, route: e.target.value })}
          />
        </div>
      )}
      <div>
        <Label htmlFor="menu-parent" className="mb-1.5 block text-zinc-700">
          父级
        </Label>
        <OptionalSelect
          value={form.parentId}
          onChange={(v) => setForm({ ...form, parentId: v })}
          options={menus.map((d) => ({ value: d.id, label: d.name }))}
          emptyLabel="作为顶级"
          id="menu-parent"
          ariaLabel="父级"
          className="h-auto w-full rounded-lg border-zinc-300 px-3 py-2"
        />
      </div>
    </FormDialogShell>
  );
}
