import { FormDialogShell } from '@/components/form-dialog-shell';
import { OptionalSelect } from '@/components/optional-select';
import { api, errMsgOf } from '@/lib/api';
import { useState } from 'react';
import { Input, Label, Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from 'ui';
import { ROLE_LABEL } from './role-label';
import { DEPTS, LEVELS } from './vocab';

interface Props {
  /** 可分配角色(来自角色列表,动态;含自定义角色)。 */
  roles: string[];
  onMsg: (m: string) => void;
  onClose: () => void;
}

const EMPTY = { email: '', displayName: '', role: 'sales_viewer', dept: '', level: '' };

/** 邀请员工弹窗:角色下拉动态取自角色列表;新员工以种子密码可真实登录;
 * 部门/职级为责任人路由人事属性(可空,走 OptionalSelect)。 */
export function StaffInviteDialog({ roles, onMsg, onClose }: Props) {
  const [invite, setInvite] = useState(EMPTY);

  const roleLabel = (r: string) => ROLE_LABEL[r] || r;

  return (
    <FormDialogShell
      title="邀请员工"
      subtitle="新员工以邮箱 + 种子密码(agent-all-dev)可真实登录"
      maxWidth="max-w-md"
      submitLabel="邀请"
      submitDisabled={!invite.email.includes('@')}
      onClose={onClose}
      onSubmit={async () => {
        const body = await api.staff.invite({
          ...invite,
          dept: invite.dept || undefined,
          level: invite.level || undefined,
        });
        if (!body.success) return errMsgOf(body);
        onMsg(`✓ 已邀请 ${String(body.email)}(${String(body.role)})`);
        return null;
      }}
    >
      <div>
        <Label htmlFor="invite-email" className="mb-1.5 block text-zinc-700">
          邮箱
        </Label>
        <Input
          id="invite-email"
          type="email"
          className="h-auto w-full rounded-lg border-zinc-300 px-3 py-2 shadow-none focus-visible:ring-0"
          placeholder="name@aurora"
          value={invite.email}
          onChange={(e) => setInvite({ ...invite, email: e.target.value })}
        />
      </div>
      <div>
        <Label htmlFor="invite-name" className="mb-1.5 block text-zinc-700">
          姓名
        </Label>
        <Input
          id="invite-name"
          className="h-auto w-full rounded-lg border-zinc-300 px-3 py-2 shadow-none focus-visible:ring-0"
          placeholder="员工姓名"
          value={invite.displayName}
          onChange={(e) => setInvite({ ...invite, displayName: e.target.value })}
        />
      </div>
      <div>
        <Label htmlFor="invite-role" className="mb-1.5 block text-zinc-700">
          角色
        </Label>
        <Select value={invite.role} onValueChange={(v) => setInvite({ ...invite, role: v })}>
          <SelectTrigger
            id="invite-role"
            aria-label="角色"
            className="h-auto w-full rounded-lg border-zinc-300 px-3 py-2"
          >
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
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <Label htmlFor="invite-dept" className="mb-1.5 block text-zinc-700">
            部门
          </Label>
          <OptionalSelect
            value={invite.dept}
            onChange={(v) => setInvite({ ...invite, dept: v })}
            options={DEPTS.map((d) => ({ value: d, label: d }))}
            emptyLabel="部门未分配"
            id="invite-dept"
            ariaLabel="部门"
            className="h-auto w-full rounded-lg border-zinc-300 px-3 py-2"
          />
        </div>
        <div>
          <Label htmlFor="invite-level" className="mb-1.5 block text-zinc-700">
            职级
          </Label>
          <OptionalSelect
            value={invite.level}
            onChange={(v) => setInvite({ ...invite, level: v })}
            options={LEVELS.map((l) => ({ value: l, label: l }))}
            emptyLabel="职级未定"
            id="invite-level"
            ariaLabel="职级"
            className="h-auto w-full rounded-lg border-zinc-300 px-3 py-2"
          />
        </div>
      </div>
    </FormDialogShell>
  );
}
