import { Button } from 'ui';
import { api } from '@/lib/api';
import { ROLE_LABEL } from './role-label';

export interface StaffRow {
  id: string;
  email: string;
  displayName: string;
  role: string;
  status: string;
}

interface Props {
  staff: StaffRow[];
  onMsg: (m: string) => void;
  onChanged: () => void;
}

/** 员工表:角色下拉改即存、停用/启用(老板账号服务端护栏)。 */
export function StaffTable({ staff, onMsg, onChanged }: Props) {
  async function patch(id: string, payload: object) {
    const body = await api.staff.update(id, payload);
    onMsg(body.success ? '✓ 已更新' : `失败:${body.message}`);
    if (body.success) onChanged();
  }

  return (
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
  );
}
