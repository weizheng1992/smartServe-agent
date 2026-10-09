import { type MenuNode, api } from '@/lib/api';
import { useEffect, useState } from 'react';
import { Button, Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from 'ui';
import { PermTree } from './perm-tree';

interface Props {
  role: string;
  tree: MenuNode[];
  onSaved: (msg: string) => void;
  onClose: () => void;
}

/** 已有角色的权限分配弹窗:打开即回填该角色当前勾选态,保存即生效。 */
export function RoleAssignDialog({ role, tree, onSaved, onClose }: Props) {
  const [sel, setSel] = useState<Set<string>>(new Set());

  useEffect(() => {
    let alive = true;
    void api.roles.menusOf(role).then((detail) => {
      if (alive) setSel(new Set(detail.menuIds));
    });
    return () => {
      alive = false;
    };
  }, [role]);

  async function save() {
    const body = await api.roles.saveMenus(role, [...sel]);
    onSaved(body.success ? `✓ 角色「${role}」权限已更新,保存即生效` : `失败:${body.message}`);
    if (body.success) onClose();
  }

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-lg rounded-xl border-zinc-200 text-zinc-900 shadow-xl">
        <DialogHeader className="pb-3 border-b border-zinc-100">
          <DialogTitle className="text-base font-bold text-zinc-900">分配权限 · {role}</DialogTitle>
          <p className="mt-1 text-xs text-zinc-500">
            勾选菜单决定侧边栏可见性;勾选按钮(权限点)决定接口动作,保存即生效。老板角色的系统菜单由服务端强制回补。
          </p>
        </DialogHeader>
        <div className="min-h-0 flex-1 overflow-y-auto py-4">
          <PermTree nodes={tree} selected={sel} onChange={setSel} />
        </div>
        <DialogFooter className="gap-2 pt-3 sm:gap-0 border-t border-zinc-100">
          <Button type="button" variant="outline" size="sm" onClick={onClose} className="text-xs cursor-pointer">
            取消
          </Button>
          <Button
            type="button"
            size="sm"
            disabled={sel.size === 0}
            onClick={() => void save()}
            className="text-xs font-bold cursor-pointer"
          >
            保存分配
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
