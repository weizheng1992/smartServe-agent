import { useCallback, useEffect, useState } from 'react';
import { api } from '@/lib/api';
import { StaffInviteForm } from './components/staff-invite-form';
import { StaffTable, type StaffRow } from './components/staff-table';

// 员工管理:邀请(角色下拉动态)/ 三维筛选 / 改角色 / 停用启用。
// 页面只做编排;表单/表格/筛选逻辑拆在同目录 components|filters 下。
export default function StaffPage() {
  const [staff, setStaff] = useState<StaffRow[]>([]);
  const [roles, setRoles] = useState<string[]>(['finance_owner', 'sales_viewer', 'warehouse_operator']);
  const [msg, setMsg] = useState('');

  const load = useCallback(async () => {
    setStaff((await api.staff.list()).staff || []);
    setRoles((await api.roles.list()).roles.map((r) => r.role));
  }, []);
  useEffect(() => { void load(); }, [load]);

  return (
    <div className="mx-auto max-w-4xl space-y-4">
      <StaffInviteForm roles={roles} onMsg={setMsg} onCreated={() => void load()} />
      <StaffTable staff={staff} roles={roles} onMsg={setMsg} onChanged={() => void load()} />
      {msg && <div className="text-[11px] text-zinc-400">{msg}</div>}
    </div>
  );
}
