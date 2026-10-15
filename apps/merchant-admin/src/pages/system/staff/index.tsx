import { api } from '@/lib/api';
import { useListPage } from '@/lib/use-list-page';
import { useState } from 'react';
import { Button } from 'ui';
import { StaffInviteDialog } from './components/staff-invite-form';
import { type StaffRow, StaffTable } from './components/staff-table';

// 员工管理:邀请(弹窗,角色下拉动态)/ 三维筛选 / 改角色 / 停用启用。
// 页面只做编排;表单/表格/筛选逻辑拆在同目录 components|filters 下。
export default function StaffPage() {
  const [roles, setRoles] = useState<string[]>(['finance_owner', 'sales_viewer', 'warehouse_operator']);
  const [inviting, setInviting] = useState(false);
  const {
    rows: staff,
    msg,
    setMsg,
    reload,
  } = useListPage<StaffRow>(async () => {
    // 次级资源(角色闭集)在 loader 闭包内就地 set
    setRoles((await api.roles.list()).roles.map((r) => r.role));
    return (await api.staff.list()).staff || [];
  });

  return (
    <div className="mx-auto max-w-4xl space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <div className="text-sm font-medium">员工管理</div>
          <div className="mt-0.5 text-xs text-zinc-400">邀请入职、角色分派与在职状态</div>
        </div>
        <Button size="sm" onClick={() => setInviting(true)}>
          + 邀请员工
        </Button>
      </div>
      <StaffTable staff={staff} roles={roles} onMsg={setMsg} onChanged={() => void reload()} />
      {inviting && (
        <StaffInviteDialog
          roles={roles}
          onMsg={setMsg}
          onClose={() => {
            setInviting(false);
            void reload();
          }}
        />
      )}
      {msg && <div className="text-[11px] text-zinc-400">{msg}</div>}
    </div>
  );
}
