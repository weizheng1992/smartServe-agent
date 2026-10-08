import { api } from '@/lib/api';
import { useState } from 'react';
import { Button } from 'ui';
import { ROLE_LABEL } from './role-label';

interface Props {
  /** 可分配角色(来自角色列表,动态;含自定义角色)。 */
  roles: string[];
  onMsg: (m: string) => void;
  onCreated: () => void;
}

const DEPTS = ['销售部', '运营部', '售后部', '财务部', '仓储部'];
const LEVELS = ['店长', '主管', '专员'];

/** 邀请员工:角色下拉动态取自角色列表;新员工以种子密码可真实登录;
 * 部门/职级为责任人路由人事属性(可空)。 */
export function StaffInviteForm({ roles, onMsg, onCreated }: Props) {
  const [invite, setInvite] = useState({ email: '', displayName: '', role: 'sales_viewer', dept: '', level: '' });

  async function submit() {
    const body = await api.staff.invite({
      ...invite,
      dept: invite.dept || undefined,
      level: invite.level || undefined,
    });
    onMsg(body.success ? `✓ 已邀请 ${String(body.email)}(${String(body.role)})` : `失败:${body.message}`);
    if (body.success) {
      setInvite({ email: '', displayName: '', role: 'sales_viewer', dept: '', level: '' });
      onCreated();
    }
  }

  const roleLabel = (r: string) => ROLE_LABEL[r] || r;

  return (
    <div className="rounded-xl border border-zinc-200 bg-white p-4">
      <div className="text-sm font-medium">邀请员工</div>
      <div className="mt-3 flex flex-wrap items-center gap-2 text-xs">
        <input
          className="w-48 rounded-lg border border-zinc-300 px-3 py-2"
          placeholder="邮箱"
          value={invite.email}
          onChange={(e) => setInvite({ ...invite, email: e.target.value })}
        />
        <input
          className="w-32 rounded-lg border border-zinc-300 px-3 py-2"
          placeholder="姓名"
          value={invite.displayName}
          onChange={(e) => setInvite({ ...invite, displayName: e.target.value })}
        />
        <select
          aria-label="角色"
          className="rounded-lg border border-zinc-300 px-3 py-2"
          value={invite.role}
          onChange={(e) => setInvite({ ...invite, role: e.target.value })}
        >
          {roles.map((r) => (
            <option key={r} value={r}>
              {roleLabel(r)}
            </option>
          ))}
        </select>
        <select
          aria-label="部门"
          className="rounded-lg border border-zinc-300 px-3 py-2"
          value={invite.dept}
          onChange={(e) => setInvite({ ...invite, dept: e.target.value })}
        >
          <option value="">部门未分配</option>
          {DEPTS.map((d) => (
            <option key={d} value={d}>
              {d}
            </option>
          ))}
        </select>
        <select
          aria-label="职级"
          className="rounded-lg border border-zinc-300 px-3 py-2"
          value={invite.level}
          onChange={(e) => setInvite({ ...invite, level: e.target.value })}
        >
          <option value="">职级未定</option>
          {LEVELS.map((l) => (
            <option key={l} value={l}>
              {l}
            </option>
          ))}
        </select>
        <Button size="sm" disabled={!invite.email.includes('@')} onClick={() => void submit()}>
          邀请
        </Button>
      </div>
    </div>
  );
}
