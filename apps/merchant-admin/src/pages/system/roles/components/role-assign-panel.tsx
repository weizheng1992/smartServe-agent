import { type MenuNode, api } from '@/lib/api';
import { useEffect, useState } from 'react';
import { Button } from 'ui';
import { PermTree } from './perm-tree';

interface Props {
  role: string;
  tree: MenuNode[];
  onSaved: (msg: string) => void;
  onCancel: () => void;
}

/** 已有角色的权限分配面板:挂载即回填该角色当前勾选态,保存即生效。 */
export function RoleAssignPanel({ role, tree, onSaved, onCancel }: Props) {
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
    if (body.success) onCancel();
  }

  return (
    <div className="rounded-xl border border-zinc-200 bg-white p-4">
      <div className="text-sm font-medium">分配权限 · {role}</div>
      <div className="mt-1 text-[11px] text-zinc-400">
        勾选菜单决定侧边栏可见性;勾选按钮(权限点)决定接口动作,保存即生效。老板角色的系统菜单由服务端强制回补。
      </div>
      <div className="mt-3">
        <PermTree nodes={tree} selected={sel} onChange={setSel} />
      </div>
      <div className="mt-3 flex items-center gap-2">
        <Button size="sm" disabled={sel.size === 0} onClick={() => void save()}>
          保存分配
        </Button>
        <Button size="sm" variant="ghost" onClick={onCancel}>
          取消
        </Button>
      </div>
    </div>
  );
}
