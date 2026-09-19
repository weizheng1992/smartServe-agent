// 员工列表筛选纯逻辑(独立模块便于单测)。
export interface StaffLike {
  id: string;
  email: string;
  displayName: string;
  role: string;
  status: string;
}

export type StaffStatusFilter = 'ALL' | 'enabled' | 'disabled';

export interface StaffFilter {
  query: string;
  role: string; // 'ALL' 或具体角色 id
  status: StaffStatusFilter;
}

export function filterStaff(staff: StaffLike[], f: StaffFilter): StaffLike[] {
  return staff.filter((s) => {
    if (f.role !== 'ALL' && s.role !== f.role) return false;
    if (f.status !== 'ALL' && s.status !== f.status) return false;
    if (f.query.trim()) {
      const q = f.query.toLowerCase().trim();
      const hit = `${s.displayName} ${s.email}`.toLowerCase().includes(q);
      if (!hit) return false;
    }
    return true;
  });
}
