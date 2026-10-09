import '@testing-library/jest-dom/vitest';
import { selectComboboxOption, selectRadixOption } from '@/test/radix-select';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import OwnerMappingsPage from './index';

// 责任人维护页(零 DB):api 域对象全桩 —— 页面只做编排,断言编排与呈现。
const listMock = vi.fn();
const upsertMock = vi.fn();
const removeMock = vi.fn();
const staffListMock = vi.fn();

vi.mock('@/lib/api', () => ({
  api: {
    ownerMappings: {
      list: (...a: unknown[]) => listMock(...a),
      upsert: (...a: unknown[]) => upsertMock(...a),
      remove: (...a: unknown[]) => removeMock(...a),
    },
    staff: { list: (...a: unknown[]) => staffListMock(...a) },
  },
}));

const mapping = (over: Partial<Record<string, unknown>> = {}) => ({
  mapType: 'category',
  mapValue: '户外机能',
  staffId: 'staff_sales_1',
  ownerType: 'business',
  updatedAt: '2026-10-08T00:00:00',
  displayName: '李芸',
  dept: '销售部',
  level: '专员',
  enabled: true,
  ...over,
});

beforeEach(() => {
  vi.clearAllMocks();
  listMock.mockResolvedValue({
    success: true,
    mappings: [
      mapping(),
      mapping({
        mapType: 'metric',
        mapValue: 'refund_rate',
        staffId: 'staff_aftersale_lead',
        displayName: '吴敏',
        dept: '售后部',
        level: '主管',
      }),
      mapping({ mapValue: '衬衫', staffId: 'staff_gone', displayName: null, enabled: false }),
    ],
    categories: ['户外机能', '潮流T恤'],
    metrics: [
      { key: 'gmv', label: '总销售额 (GMV)' },
      { key: 'refund_rate', label: '退款率' },
    ],
  });
  staffListMock.mockResolvedValue({
    success: true,
    staff: [
      {
        id: 'staff_sales_1',
        email: 'sales1@aurora',
        displayName: '李芸',
        role: 'sales_viewer',
        status: 'enabled',
        dept: '销售部',
        level: '专员',
      },
      {
        id: 'staff_aftersale_lead',
        email: 'as_lead@aurora',
        displayName: '吴敏',
        role: 'support_agent',
        status: 'enabled',
        dept: '售后部',
        level: '主管',
      },
      {
        id: 'staff_gone',
        email: 'gone@aurora',
        displayName: '旧人',
        role: 'sales_viewer',
        status: 'disabled',
        dept: '销售部',
        level: '专员',
      },
    ],
  });
});

describe('OwnerMappingsPage(责任人维护)', () => {
  it('渲染映射表:类型中文化 / 负责人带部门·职级 / 停用员工标停用', async () => {
    render(<OwnerMappingsPage />);
    await waitFor(() => expect(screen.getByText('已登记映射(3)')).toBeInTheDocument());
    // 表格行与下拉选项同文(品类名/负责人名都出现在两处),用 getAllByText 断言存在
    expect(screen.getAllByText('户外机能').length).toBeGreaterThan(0);
    expect(screen.getAllByText('李芸(销售部·专员)').length).toBeGreaterThan(0);
    expect(screen.getAllByText('吴敏(售后部·主管)').length).toBeGreaterThan(0);
    expect(screen.getByText('已停用')).toBeInTheDocument();
    expect(screen.getAllByText('衬衫').length).toBeGreaterThan(0); // 停用员工的映射仍列示
  });

  it('登记:类型切指标 → 维度值下拉换指标闭集;提交携带三元组', async () => {
    upsertMock.mockResolvedValue({ success: true, mapType: 'metric', mapValue: 'gmv', staffId: 'staff_sales_lead' });
    render(<OwnerMappingsPage />);
    await waitFor(() => expect(screen.getByText('已登记映射(3)')).toBeInTheDocument());

    // 登记走弹窗(全站新增/编辑弹窗化)
    fireEvent.click(screen.getByRole('button', { name: '+ 登记 / 改派' }));
    await screen.findByText('登记 / 改派责任人');

    // Radix Select(ui)+ 可搜索下拉(SearchableSelect):开层点选;
    // 「下拉吃语义注册表闭集,前端零硬编码」由 option 文案断言承载
    // (旧版遍历 HTMLSelectElement.options 的等价改写)
    await selectRadixOption('映射类型', '指标');
    await selectComboboxOption('维度值', /总销售额/); // gmv 的人话 label 含「总销售额」
    await selectRadixOption('负责人', /吴敏/); // staff_aftersale_lead = 售后部主管
    fireEvent.click(screen.getByRole('button', { name: '登记' }));

    await waitFor(() =>
      expect(upsertMock).toHaveBeenCalledWith({ mapType: 'metric', mapValue: 'gmv', staffId: 'staff_aftersale_lead' }),
    );
    expect(listMock).toHaveBeenCalledTimes(2); // 登记成功后重拉
  });

  it('撤销:按 mapType+mapValue 删除并刷新', async () => {
    removeMock.mockResolvedValue({ success: true });
    render(<OwnerMappingsPage />);
    await waitFor(() => expect(screen.getAllByText('户外机能').length).toBeGreaterThan(0));
    fireEvent.click(screen.getAllByRole('button', { name: '撤销' })[0]);
    await waitFor(() => expect(removeMock).toHaveBeenCalledWith('category', '户外机能'));
    expect(listMock).toHaveBeenCalledTimes(2);
  });
});
