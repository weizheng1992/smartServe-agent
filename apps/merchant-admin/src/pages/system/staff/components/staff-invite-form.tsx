import { useState } from 'react';
import { Button } from 'ui';
import { api } from '@/lib/api';
import { ROLE_LABEL } from './role-label';

interface Props {
  onMsg: (m: string) => void;
  onCreated: () => void;
}

/** 邀请员工:邀请即建号(以种子密码可真实登录,角色下拉选定)。 */
export function StaffInviteForm({ onMsg, onCreated }: Props) {
  const [invite, setInvite] = useState({ email: '', displayName: '', role: 'sales_viewer' });

  async function submit() {
    const body = await api.staff.invite(invite);
    onMsg(body.success ? `✓ 已邀请 ${String(body.email)}(${String(body.role)})` : `失败:${body.message}`);
    if (body.success) {
      setInvite({ email: '', displayName: '', role: 'sales_viewer' });
      onCreated();
    }
  }

  return (
    <div className="rounded-xl border border-zinc-200 bg-white p-4">
      <div className="text-sm font-medium">邀请员工</div>
      <div className="mt-3 flex flex-wrap items-center gap-2 text-xs">
        <input className="w-48 rounded-lg border border-zinc-300 px-3 py-2" placeholder="邮箱" value={invite.email} onChange={(e) => setInvite({ ...invite, email: e.target.value })} />
        <input className="w-32 rounded-lg border border-zinc-300 px-3 py-2" placeholder="姓名" value={invite.displayName} onChange={(e) => setInvite({ ...invite, displayName: e.target.value })} />
        <select className="rounded-lg border border-zinc-300 px-3 py-2" value={invite.role} onChange={(e) => setInvite({ ...invite, role: e.target.value })}>
          {Object.entries(ROLE_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
        <Button size="sm" disabled={!invite.email.includes('@')} onClick={() => void submit()}>邀请</Button>
      </div>
    </div>
  );
}
