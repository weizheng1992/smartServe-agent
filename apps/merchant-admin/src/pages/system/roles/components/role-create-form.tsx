import { type MenuNode, api } from '@/lib/api';
import { useState } from 'react';
import { Button, Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle, Input, Label } from 'ui';
import { PermTree } from './perm-tree';

interface Props {
  tree: MenuNode[];
  onMsg: (m: string) => void;
  onClose: () => void;
}

const DEFAULT_PICK = ['m-analytics'];

/** 新建自定义角色弹窗:角色标识 + 权限勾选树(与再分配同一棵树)。 */
export function RoleCreateDialog({ tree, onMsg, onClose }: Props) {
  const [newRole, setNewRole] = useState('');
  const [sel, setSel] = useState<Set<string>>(new Set(DEFAULT_PICK));

  async function create() {
    const body = await api.roles.create(newRole, [...sel]);
    onMsg(body.success ? `✓ 角色「${body.role}」已建(${body.menuCount} 菜单)` : `失败:${body.message}`);
    if (body.success) onClose();
  }

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-lg rounded-xl border-zinc-200 text-zinc-900 shadow-xl">
        <DialogHeader className="pb-3 border-b border-zinc-100">
          <DialogTitle className="text-base font-bold text-zinc-900">新建自定义角色</DialogTitle>
          <p className="mt-1 text-xs text-zinc-500">
            指标权限:默认沿用运营口径;在「菜单管理」给数据菜单挂 `metric:指标名` 按钮(如
            metric:gmv)并勾给角色,即可自定义可见指标。
          </p>
        </DialogHeader>
        <div className="min-h-0 flex-1 space-y-3 overflow-y-auto py-4 text-xs">
          <div>
            <Label htmlFor="role-key" className="mb-1.5 block text-zinc-700">
              角色标识
            </Label>
            <Input
              id="role-key"
              className="h-auto w-full rounded-lg border-zinc-300 px-3 py-2 shadow-none focus-visible:ring-0"
              placeholder="如 custom_ops"
              value={newRole}
              onChange={(e) => setNewRole(e.target.value)}
            />
          </div>
          <PermTree nodes={tree} selected={sel} onChange={setSel} />
          <div className="text-[11px] text-zinc-400">
            创建后到「员工管理」给员工分派该角色;员工在登录页以邮箱 + 种子密码(agent-all-dev)登录。
          </div>
        </div>
        <DialogFooter className="gap-2 pt-3 sm:gap-0 border-t border-zinc-100">
          <Button type="button" variant="outline" size="sm" onClick={onClose} className="text-xs cursor-pointer">
            取消
          </Button>
          <Button
            type="button"
            size="sm"
            disabled={!newRole || sel.size === 0}
            onClick={() => void create()}
            className="text-xs font-bold cursor-pointer"
          >
            创建
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
