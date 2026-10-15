import { FormDialogShell } from '@/components/form-dialog-shell';
import { type MenuNode, api, errMsgOf } from '@/lib/api';
import { useEffect, useState } from 'react';
import { PermTree } from './perm-tree';

interface Props {
  role: string;
  tree: MenuNode[];
  onMsg: (m: string) => void;
  onClose: () => void;
}

/** 已有角色的权限分配弹窗:打开即回填该角色当前勾选态,保存即生效。
 *  (props 命名收敛:onSaved → onMsg,2026-10-15 候选④。) */
export function RoleAssignDialog({ role, tree, onMsg, onClose }: Props) {
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

  return (
    <FormDialogShell
      title={`分配权限 · ${role}`}
      subtitle="勾选菜单决定侧边栏可见性;勾选按钮(权限点)决定接口动作,保存即生效。老板角色的系统菜单由服务端强制回补。"
      maxWidth="max-w-lg"
      submitLabel="保存分配"
      submitDisabled={sel.size === 0}
      onClose={onClose}
      onSubmit={async () => {
        const body = await api.roles.saveMenus(role, [...sel]);
        if (!body.success) return errMsgOf(body);
        onMsg(`✓ 角色「${role}」权限已更新,保存即生效`);
        return null;
      }}
    >
      <PermTree nodes={tree} selected={sel} onChange={setSel} />
    </FormDialogShell>
  );
}
