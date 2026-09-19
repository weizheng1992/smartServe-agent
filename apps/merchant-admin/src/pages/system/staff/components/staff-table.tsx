import { useState } from 'react';
import { Button } from 'ui';
import { api } from '@/lib/api';
import { filterStaff, type StaffFilter, type StaffStatusFilter } from '../filters';
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
  /** 全部可选角色(角色列表动态拉取)。 */
  roles: string[];
  onMsg: (m: string) => void;
  onChanged: () => void;
}

const STATUS_FILTERS: Array<{ key: StaffStatusFilter; label: string }> = [
  { key: 'ALL', label: '全部状态' },
  { key: 'enabled', label: '启用' },
  { key: 'disabled', label: '停用' },
];

const roleLabel = (r: string) => ROLE_LABEL[r] || r;

/** 员工表:关键词(姓名/邮箱)+ 角色 + 状态三维筛选;角色改即存;停用有服务端护栏。 */
export function StaffTable({ staff, roles, onMsg, onChanged }: Props) {
  const [filter, setFilter] = useState<StaffFilter>({ query: '', role: 'ALL', status: 'ALL' });

  async function patch(id: string, payload: object) {
    const body = await api.staff.update(id, payload);
    onMsg(body.success ? '✓ 已更新' : `失败:${body.message}`);
    if (body.success) onChanged();
  }

  const rows = filterStaff(staff, filter);

  return (
    <div className="overflow-hidden rounded-xl border border-zinc-200 bg-white">
      <div className="flex flex-wrap items-center gap-2 border-b border-zinc-100 bg-zinc-50/70 px-4 py-3 text-xs">
        <input
          className="w-52 rounded-lg border border-zinc-300 px-3 py-1.5"
          placeholder="搜索姓名 / 邮箱"
          value={filter.query}
          onChange={(e) => setFilter({ ...filter, query: e.target.value })}
        />
        <select className="rounded-lg border border-zinc-300 px-2 py-1.5" value={filter.role} onChange={(e) => setFilter({ ...filter, role: e.target.value })}>
          <option value="ALL">全部角色</option>
          {roles.map((r) => <option key={r} value={r}>{roleLabel(r)}</option>)}
        </select>
        <select className="rounded-lg border border-zinc-300 px-2 py-1.5" value={filter.status} onChange={(e) => setFilter({ ...filter, status: e.target.value as StaffStatusFilter })}>
          {STATUS_FILTERS.map((s) => <option key={s.key} value={s.key}>{s.label}</option>)}
        </select>
        <span className="text-[11px] text-zinc-400">{rows.length} / {staff.length} 人</span>
      </div>
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
          {rows.length === 0 && (
            <tr><td colSpan={4} className="px-4 py-6 text-center text-xs text-zinc-400">无匹配员工(诚实空)</td></tr>
          )}
          {rows.map((s) => (
            <tr key={s.id} className="border-b border-zinc-50">
              <td className="px-4 py-2">{s.displayName}<span className="ml-2 text-[11px] text-zinc-400">{s.email}</span></td>
              <td className="px-4 py-2">
                <select
                  className="rounded-lg border border-zinc-300 px-2 py-1 text-xs"
                  defaultValue={s.role}
                  onChange={(e) => void patch(s.id, { role: e.target.value })}
                >
                  {[...new Set([...roles, s.role])].map((r) => <option key={r} value={r}>{roleLabel(r)}</option>)}
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
