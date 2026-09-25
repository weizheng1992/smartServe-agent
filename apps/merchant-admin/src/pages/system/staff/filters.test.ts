import { describe, expect, it } from 'vitest';
import { type StaffLike, filterStaff } from './filters';

const s = (over: Partial<StaffLike>): StaffLike => ({
  id: over.id || 'staff_x',
  email: over.email || 'x@aurora',
  displayName: over.displayName || '小明',
  role: over.role || 'sales_viewer',
  status: over.status || 'enabled',
  ...over,
});

const staff = [
  s({ id: '1', displayName: '老板', email: 'test@example.com', role: 'finance_owner', status: 'enabled' }),
  s({ id: '2', displayName: '运营小王', email: 'ops@aurora', role: 'sales_viewer', status: 'enabled' }),
  s({ id: '3', displayName: '仓储老李', email: 'wh@aurora', role: 'warehouse_operator', status: 'disabled' }),
  s({ id: '4', displayName: '客服一号', email: 'custom@aurora', role: 'custom_desk', status: 'enabled' }),
];

describe('filterStaff', () => {
  it('全默认返回全量', () => {
    expect(filterStaff(staff, { query: '', role: 'ALL', status: 'ALL' })).toHaveLength(4);
  });

  it('关键词命中姓名或邮箱,不分大小写', () => {
    expect(filterStaff(staff, { query: 'OPS', role: 'ALL', status: 'ALL' }).map((x) => x.id)).toEqual(['2']);
    expect(filterStaff(staff, { query: 'example.com', role: 'ALL', status: 'ALL' }).map((x) => x.id)).toEqual(['1']);
  });

  it('按角色/状态过滤,三维可叠加', () => {
    expect(filterStaff(staff, { query: '', role: 'sales_viewer', status: 'ALL' }).map((x) => x.id)).toEqual(['2']);
    expect(filterStaff(staff, { query: '', role: 'ALL', status: 'disabled' }).map((x) => x.id)).toEqual(['3']);
    expect(filterStaff(staff, { query: '小', role: 'sales_viewer', status: 'enabled' }).map((x) => x.id)).toEqual([
      '2',
    ]);
  });

  it('无匹配诚实空', () => {
    expect(filterStaff(staff, { query: '不存在', role: 'ALL', status: 'ALL' })).toEqual([]);
  });
});
