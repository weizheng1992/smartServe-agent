import { useCallback, useEffect, useState } from 'react';
import { Button } from 'ui';
import { authHeaders } from '@/lib/api';

interface Staff {
  id: string;
  email: string;
  displayName: string;
  role: string;
  status: string;
}

const ROLE_LABEL: Record<string, string> = {
  finance_owner: '老板',
  sales_viewer: '运营',
  warehouse_operator: '仓储',
};

// 员工管理(13 号):邀请 / 改角色 / 停用(老板账号服务端护栏)。
export default function StaffPage() {
  const [staff, setStaff] = useState<Staff[]>([]);
  const [msg, setMsg] = useState('');
  const [invite, setInvite] = useState({ email: '', displayName: '', role: 'sales_viewer' });

  const H = authHeaders;
  const load = useCallback(async () => {
    const res = await fetch('/api/admin/analytics/staff', { headers: H() });
    setStaff((await res.json()).staff || []);
  }, []);
  useEffect(() => { void load(); }, [load]);

  async function submitInvite() {
    const res = await fetch('/api/admin/analytics/staff', { method: 'POST', headers: H(), body: JSON.stringify(invite) });
    const body = await res.json();
    setMsg(body.success ? `✓ 已邀请 ${String(body.email)}(${String(body.role)})` : `失败:${body.message}`);
    if (body.success) { setInvite({ email: '', displayName: '', role: 'sales_viewer' }); void load(); }
  }

  async function patch(id: string, payload: object) {
    const res = await fetch(`/api/admin/analytics/staff/${id}`, { method: 'PATCH', headers: H(), body: JSON.stringify(payload) });
    const body = await res.json();
    setMsg(body.success ? '✓ 已更新' : `失败:${body.message}`);
    if (body.success) void load();
  }

  return (
    <div className="mx-auto max-w-4xl space-y-4">
      <div className="rounded-xl border border-zinc-200 bg-white p-4">
        <div className="text-sm font-medium">邀请员工</div>
        <div className="mt-3 flex flex-wrap items-center gap-2 text-xs">
          <input className="w-48 rounded-lg border border-zinc-300 px-3 py-2" placeholder="邮箱" value={invite.email} onChange={(e) => setInvite({ ...invite, email: e.target.value })} />
          <input className="w-32 rounded-lg border border-zinc-300 px-3 py-2" placeholder="姓名" value={invite.displayName} onChange={(e) => setInvite({ ...invite, displayName: e.target.value })} />
          <select className="rounded-lg border border-zinc-300 px-3 py-2" value={invite.role} onChange={(e) => setInvite({ ...invite, role: e.target.value })}>
            {Object.entries(ROLE_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
          <Button size="sm" disabled={!invite.email.includes('@')} onClick={() => void submitInvite()}>邀请</Button>
          {msg && <span className="text-[11px] text-zinc-400">{msg}</span>}
        </div>
      </div>

      <div className="overflow-hidden rounded-xl border border-zinc-200 bg-white">
        <table className="w-full text-[13px]">
          <thead>
            <tr className="border-b border-zinc-100 text-left text-zinc-400">
              <th className="px-4 py-2 font-medium">员工</th>
              <th className="px-4 py-2 font-medium">角色</th>
              <th className="px-4 py-2 font-medium">状态</th>
              <th className="px-4 py-2 font-medium">操作</th>
            </tr>
          </thead>
          <tbody>
            {staff.map((s) => (
              <tr key={s.id} className="border-b border-zinc-50">
                <td className="px-4 py-2">{s.displayName}<span className="ml-2 text-[11px] text-zinc-400">{s.email}</span></td>
                <td className="px-4 py-2">
                  <select
                    className="rounded-lg border border-zinc-300 px-2 py-1 text-xs"
                    defaultValue={s.role}
                    onChange={(e) => void patch(s.id, { role: e.target.value })}
                  >
                    {Object.entries(ROLE_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                    {s.role.startsWith('custom_') && <option value={s.role}>{s.role}</option>}
                  </select>
                </td>
                <td className="px-4 py-2">{s.status === 'enabled' ? '启用' : '停用'}</td>
                <td className="px-4 py-2">
                  {s.role !== 'finance_owner' && (
                    <Button size="sm" variant="ghost" onClick={() => void patch(s.id, { status: s.status === 'enabled' ? 'disabled' : 'enabled' })}>
                      {s.status === 'enabled' ? '停用' : '启用'}
                    </Button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
