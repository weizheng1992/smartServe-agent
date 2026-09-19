import { useCallback, useEffect, useState } from 'react';
import { api } from '@/lib/api';
import { StaffInviteForm } from './components/staff-invite-form';
import { StaffTable, type StaffRow } from './components/staff-table';

// 员工管理(13 号):邀请 / 改角色 / 停用(老板账号服务端护栏)。
// 页面只做编排;邀请表单与员工表拆在同目录 components/ 下。
export default function StaffPage() {
  const [staff, setStaff] = useState<StaffRow[]>([]);
  const [msg, setMsg] = useState('');

  const load = useCallback(async () => {
    setStaff((await api.staff.list()).staff || []);
  }, []);
  useEffect(() => { void load(); }, [load]);

  return (
    <div className="mx-auto max-w-4xl space-y-4">
      <StaffInviteForm onMsg={setMsg} onCreated={() => void load()} />
      <StaffTable staff={staff} onMsg={setMsg} onChanged={() => void load()} />
      {msg && <div className="text-[11px] text-zinc-400">{msg}</div>}
    </div>
  );
}
