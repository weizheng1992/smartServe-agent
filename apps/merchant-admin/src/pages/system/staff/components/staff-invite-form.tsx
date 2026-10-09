import { api } from '@/lib/api';
import { useState } from 'react';
import { Button, Input, Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from 'ui';
import { ROLE_LABEL } from './role-label';

/** Radix SelectItem 禁空串:「部门未分配/职级未定」(invite.dept/level='')的哨兵值。 */
const UNSET = '__unset__';

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
        <Input
          className="h-auto w-48 rounded-lg border-zinc-300 px-3 py-2 text-xs shadow-none focus-visible:ring-0"
          placeholder="邮箱"
          value={invite.email}
          onChange={(e) => setInvite({ ...invite, email: e.target.value })}
        />
        <Input
          className="h-auto w-32 rounded-lg border-zinc-300 px-3 py-2 text-xs shadow-none focus-visible:ring-0"
          placeholder="姓名"
          value={invite.displayName}
          onChange={(e) => setInvite({ ...invite, displayName: e.target.value })}
        />
        <Select value={invite.role} onValueChange={(v) => setInvite({ ...invite, role: v })}>
          <SelectTrigger aria-label="角色" className="h-auto rounded-lg border-zinc-300 px-3 py-2 text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {roles.map((r) => (
              <SelectItem key={r} value={r}>
                {roleLabel(r)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select
          value={invite.dept || UNSET}
          onValueChange={(v) => setInvite({ ...invite, dept: v === UNSET ? '' : v })}
        >
          <SelectTrigger aria-label="部门" className="h-auto rounded-lg border-zinc-300 px-3 py-2 text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={UNSET}>部门未分配</SelectItem>
            {DEPTS.map((d) => (
              <SelectItem key={d} value={d}>
                {d}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select
          value={invite.level || UNSET}
          onValueChange={(v) => setInvite({ ...invite, level: v === UNSET ? '' : v })}
        >
          <SelectTrigger aria-label="职级" className="h-auto rounded-lg border-zinc-300 px-3 py-2 text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={UNSET}>职级未定</SelectItem>
            {LEVELS.map((l) => (
              <SelectItem key={l} value={l}>
                {l}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Button size="sm" disabled={!invite.email.includes('@')} onClick={() => void submit()}>
          邀请
        </Button>
      </div>
    </div>
  );
}
