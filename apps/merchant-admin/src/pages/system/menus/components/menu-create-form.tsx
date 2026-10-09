import { type MenuNode, api } from '@/lib/api';
import { useState } from 'react';
import {
  Button,
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Input,
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from 'ui';

/** Radix SelectItem 禁空串:「作为顶级」(parentId='')的哨兵值。 */
const ROOT = '__root__';

interface Props {
  menus: MenuNode[];
  onMsg: (m: string) => void;
  onClose: () => void;
}

const EMPTY = { name: '', menuType: 'menu', route: '', parentId: '', permCode: '' };

/** 新增菜单/按钮弹窗:按钮型需权限点(即角色管理页可勾选的接口权限);
 * 父级空值走 __root__ 哨兵(onValueChange 单点映射回 null 提交)。 */
export function MenuCreateDialog({ menus, onMsg, onClose }: Props) {
  const [form, setForm] = useState(EMPTY);

  async function create() {
    const body = await api.menuAdmin.create({ ...form, sort: 9, parentId: form.parentId || null });
    onMsg(body.success ? `✓ 已新增「${form.name}」` : `失败:${body.message}`);
    if (body.success) onClose();
  }

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-md rounded-xl border-zinc-200 text-zinc-900 shadow-xl">
        <DialogHeader className="pb-3 border-b border-zinc-100">
          <DialogTitle className="text-base font-bold text-zinc-900">新增菜单 / 按钮</DialogTitle>
          <p className="mt-1 text-xs text-zinc-500">
            这里登记的按钮权限点(perm_code)即角色管理页可勾选的接口权限;系统菜单由服务端护栏保护。
          </p>
        </DialogHeader>
        <div className="min-h-0 flex-1 space-y-3 overflow-y-auto py-4 text-xs">
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
            <Select
              value={form.parentId || ROOT}
              onValueChange={(v) => setForm({ ...form, parentId: v === ROOT ? '' : v })}
            >
              <SelectTrigger
                id="menu-parent"
                aria-label="父级"
                className="h-auto w-full rounded-lg border-zinc-300 px-3 py-2"
              >
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
          </div>
        </div>
        <DialogFooter className="gap-2 pt-3 sm:gap-0 border-t border-zinc-100">
          <Button type="button" variant="outline" size="sm" onClick={onClose} className="text-xs cursor-pointer">
            取消
          </Button>
          <Button
            type="button"
            size="sm"
            disabled={!form.name}
            onClick={() => void create()}
            className="text-xs font-bold cursor-pointer"
          >
            新增
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
