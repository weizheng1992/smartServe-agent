import { FormDialogShell } from '@/components/form-dialog-shell';
import { type MenuNode, api, errMsgOf } from '@/lib/api';
import { useState } from 'react';
import { Input, Label } from 'ui';
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

  return (
    <FormDialogShell
      title="新建自定义角色"
      subtitle={
        <>
          指标权限:默认沿用运营口径;在「菜单管理」给数据菜单挂 `metric:指标名` 按钮(如
          metric:gmv)并勾给角色,即可自定义可见指标。
        </>
      }
      maxWidth="max-w-lg"
      submitLabel="创建"
      submitDisabled={!newRole || sel.size === 0}
      onClose={onClose}
      onSubmit={async () => {
        const body = await api.roles.create(newRole, [...sel]);
        if (!body.success) return errMsgOf(body);
        onMsg(`✓ 角色「${body.role}」已建(${body.menuCount} 菜单)`);
        return null;
      }}
    >
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
    </FormDialogShell>
  );
}
