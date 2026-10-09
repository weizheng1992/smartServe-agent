import {
  DenseTable,
  DenseTableBody,
  DenseTableCell,
  DenseTableHead,
  DenseTableHeader,
  DenseTableRow,
} from '@/components/dense-table';
import { api } from '@/lib/api';
import { useState } from 'react';
import { Button, Input, Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from 'ui';
import { type StaffFilter, type StaffStatusFilter, filterStaff } from '../filters';
import { ROLE_LABEL } from './role-label';

/** Radix SelectItem 禁空串:「未分配/未定级」(dept/level='')的哨兵值,
 *  onValueChange 单点映射回 '' —— 哨兵严禁进 API payload。 */
const UNSET = '__unset__';

export interface StaffRow {
  id: string;
  email: string;
  displayName: string;
  role: string;
  status: string;
  dept: string | null;
  level: string | null;
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

// 部门/职级闭集(0019 人事属性;展示与责任人路由消费,不参与 RBAC 判定)。
const DEPTS = ['销售部', '运营部', '售后部', '财务部', '仓储部'];
const LEVELS = ['店长', '主管', '专员'];

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
        <Input
          className="h-auto w-52 rounded-lg border-zinc-300 px-3 py-1.5 text-xs shadow-none focus-visible:ring-0"
          placeholder="搜索姓名 / 邮箱"
          value={filter.query}
          onChange={(e) => setFilter({ ...filter, query: e.target.value })}
        />
        <Select value={filter.role} onValueChange={(v) => setFilter({ ...filter, role: v })}>
          <SelectTrigger aria-label="角色过滤" className="h-auto rounded-lg px-2 py-1.5 text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="ALL">全部角色</SelectItem>
            {roles.map((r) => (
              <SelectItem key={r} value={r}>
                {roleLabel(r)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select value={filter.status} onValueChange={(v) => setFilter({ ...filter, status: v as StaffStatusFilter })}>
          <SelectTrigger aria-label="状态过滤" className="h-auto rounded-lg px-2 py-1.5 text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {STATUS_FILTERS.map((s) => (
              <SelectItem key={s.key} value={s.key}>
                {s.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <span className="text-[11px] text-zinc-400">
          {rows.length} / {staff.length} 人
        </span>
      </div>
      <DenseTable>
        <DenseTableHeader>
          <DenseTableRow className="border-b border-zinc-100 hover:bg-transparent">
            <DenseTableHead>员工</DenseTableHead>
            <DenseTableHead>部门 / 职级</DenseTableHead>
            <DenseTableHead>角色</DenseTableHead>
            <DenseTableHead>状态</DenseTableHead>
            <DenseTableHead>操作</DenseTableHead>
          </DenseTableRow>
        </DenseTableHeader>
        <DenseTableBody>
          {rows.length === 0 && (
            <DenseTableRow>
              <DenseTableCell colSpan={5} className="py-6 text-center text-xs text-zinc-400">
                无匹配员工(诚实空)
              </DenseTableCell>
            </DenseTableRow>
          )}
          {rows.map((s) => (
            <DenseTableRow key={s.id}>
              <DenseTableCell>
                {s.displayName}
                <span className="ml-2 text-[11px] text-zinc-400">{s.email}</span>
              </DenseTableCell>
              <DenseTableCell>
                <Select value={s.dept || UNSET} onValueChange={(v) => void patch(s.id, { dept: v === UNSET ? '' : v })}>
                  <SelectTrigger
                    aria-label={`部门:${s.displayName}`}
                    className="mb-1 h-auto rounded-lg border-zinc-300 px-2 py-1 text-xs"
                  >
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value={UNSET}>未分配</SelectItem>
                    {DEPTS.map((d) => (
                      <SelectItem key={d} value={d}>
                        {d}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <Select
                  value={s.level || UNSET}
                  onValueChange={(v) => void patch(s.id, { level: v === UNSET ? '' : v })}
                >
                  <SelectTrigger
                    aria-label={`职级:${s.displayName}`}
                    className="h-auto rounded-lg border-zinc-300 px-2 py-1 text-xs"
                  >
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value={UNSET}>未定级</SelectItem>
                    {LEVELS.map((l) => (
                      <SelectItem key={l} value={l}>
                        {l}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </DenseTableCell>
              <DenseTableCell>
                <Select defaultValue={s.role} onValueChange={(v) => void patch(s.id, { role: v })}>
                  <SelectTrigger
                    aria-label={`角色:${s.displayName}`}
                    className="h-auto rounded-lg border-zinc-300 px-2 py-1 text-xs"
                  >
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {[...new Set([...roles, s.role])].map((r) => (
                      <SelectItem key={r} value={r}>
                        {roleLabel(r)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </DenseTableCell>
              <DenseTableCell>{s.status === 'enabled' ? '启用' : '停用'}</DenseTableCell>
              <DenseTableCell>
                {s.role !== 'finance_owner' && (
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => void patch(s.id, { status: s.status === 'enabled' ? 'disabled' : 'enabled' })}
                  >
                    {s.status === 'enabled' ? '停用' : '启用'}
                  </Button>
                )}
              </DenseTableCell>
            </DenseTableRow>
          ))}
        </DenseTableBody>
      </DenseTable>
    </div>
  );
}
