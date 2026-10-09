import { api } from '@/lib/api';
import { useState } from 'react';
import {
  Button,
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Input,
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from 'ui';
import { ROLE_LABEL } from './role-label';

/** Radix SelectItem 禁空串:「部门未分配/职级未定」(invite.dept/level='')的哨兵值。 */
const UNSET = '__unset__';

interface Props {
  /** 可分配角色(来自角色列表,动态;含自定义角色)。 */
  roles: string[];
  onMsg: (m: string) => void;
  onClose: () => void;
}

const DEPTS = ['销售部', '运营部', '售后部', '财务部', '仓储部'];
const LEVELS = ['店长', '主管', '专员'];

const EMPTY = { email: '', displayName: '', role: 'sales_viewer', dept: '', level: '' };

/** 邀请员工弹窗:角色下拉动态取自角色列表;新员工以种子密码可真实登录;
 * 部门/职级为责任人路由人事属性(可空,走 __unset__ 哨兵)。 */
export function StaffInviteDialog({ roles, onMsg, onClose }: Props) {
  const [invite, setInvite] = useState(EMPTY);

  async function submit() {
    const body = await api.staff.invite({
      ...invite,
      dept: invite.dept || undefined,
      level: invite.level || undefined,
    });
    onMsg(body.success ? `✓ 已邀请 ${String(body.email)}(${String(body.role)})` : `失败:${body.message}`);
    if (body.success) onClose();
  }

  const roleLabel = (r: string) => ROLE_LABEL[r] || r;

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-md rounded-xl border-zinc-200 text-zinc-900 shadow-xl">
        <DialogHeader className="pb-3 border-b border-zinc-100">
          <DialogTitle className="text-base font-bold text-zinc-900">邀请员工</DialogTitle>
          <p className="mt-1 text-xs text-zinc-500">新员工以邮箱 + 种子密码(agent-all-dev)可真实登录</p>
        </DialogHeader>
        <div className="min-h-0 flex-1 space-y-3 overflow-y-auto py-4 text-xs">
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
              <Select
                value={invite.dept || UNSET}
                onValueChange={(v) => setInvite({ ...invite, dept: v === UNSET ? '' : v })}
              >
                <SelectTrigger
                  id="invite-dept"
                  aria-label="部门"
                  className="h-auto w-full rounded-lg border-zinc-300 px-3 py-2"
                >
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
            </div>
            <div>
              <Label htmlFor="invite-level" className="mb-1.5 block text-zinc-700">
                职级
              </Label>
              <Select
                value={invite.level || UNSET}
                onValueChange={(v) => setInvite({ ...invite, level: v === UNSET ? '' : v })}
              >
                <SelectTrigger
                  id="invite-level"
                  aria-label="职级"
                  className="h-auto w-full rounded-lg border-zinc-300 px-3 py-2"
                >
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
            </div>
          </div>
        </div>
        <DialogFooter className="gap-2 pt-3 sm:gap-0 border-t border-zinc-100">
          <Button type="button" variant="outline" size="sm" onClick={onClose} className="text-xs cursor-pointer">
            取消
          </Button>
          <Button
            type="button"
            size="sm"
            disabled={!invite.email.includes('@')}
            onClick={() => void submit()}
            className="text-xs font-bold cursor-pointer"
          >
            邀请
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
