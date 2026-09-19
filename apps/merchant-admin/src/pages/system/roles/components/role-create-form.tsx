import { useState } from 'react';
import { Button } from 'ui';
import { api, type MenuNode } from '@/lib/api';
import { PermTree } from './perm-tree';

interface Props {
  tree: MenuNode[];
  onMsg: (m: string) => void;
  onCreated: () => void;
}

const DEFAULT_PICK = ['m-analytics'];

/** 新建自定义角色:角色标识 + 权限勾选树(与再分配同一棵树)。 */
export function RoleCreateForm({ tree, onMsg, onCreated }: Props) {
  const [newRole, setNewRole] = useState('');
  const [sel, setSel] = useState<Set<string>>(new Set(DEFAULT_PICK));

  async function create() {
    const body = await api.roles.create(newRole, [...sel]);
    onMsg(body.success ? `✓ 角色「${body.role}」已建(${body.menuCount} 菜单)` : `失败:${body.message}`);
    if (body.success) {
      setNewRole('');
      setSel(new Set());
      onCreated();
    }
  }

  return (
    <div className="rounded-xl border border-zinc-200 bg-white p-4">
      <div className="text-sm font-medium">新建自定义角色</div>
      <div className="mt-1 text-[11px] text-zinc-400">
        指标权限:默认沿用运营口径;在「菜单管理」给数据菜单挂 `metric:指标名` 按钮(如 metric:gmv)并勾给角色,即可自定义可见指标。
      </div>
      <div className="mt-3 flex flex-wrap items-start gap-3 text-xs">
        <div className="space-y-2">
          <input className="w-44 rounded-lg border border-zinc-300 px-3 py-2" placeholder="角色标识(如 custom_ops)" value={newRole} onChange={(e) => setNewRole(e.target.value)} />
          <div>
            <Button size="sm" disabled={!newRole || sel.size === 0} onClick={() => void create()}>创建</Button>
          </div>
        </div>
        <div className="min-w-[240px] flex-1">
          <PermTree nodes={tree} selected={sel} onChange={setSel} />
        </div>
      </div>
      <div className="mt-2 text-[11px] text-zinc-400">创建后到「员工管理」给员工分派该角色;员工在登录页以邮箱 + 种子密码(agent-all-dev)登录。</div>
    </div>
  );
}
