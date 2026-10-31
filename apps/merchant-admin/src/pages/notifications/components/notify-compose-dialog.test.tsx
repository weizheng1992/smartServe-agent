import '@testing-library/jest-dom/vitest';
import { selectRadixOption } from '@/test/radix-select';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { NotifyComposeDialog } from './notify-compose-dialog';

// 单测(不依赖网关):广播/定向两态渲染、字段闸(标题/正文长度、定向必选顾客)、
// 提交映射契约(targetType/customerId)与频控业务错误留窗(FormDialogShell 契约)。
const mocks = vi.hoisted(() => ({
  send: vi.fn(),
}));

vi.mock('@/lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api')>();
  return {
    ...actual,
    api: {
      ...actual.api,
      notifications: { ...actual.api.notifications, send: mocks.send },
    },
  };
});

const CUSTOMERS = [
  { customerId: 'CUST-8801', name: '张伟' },
  { customerId: 'CUST-8802', name: '李娜' },
];

function renderDialog(props: Partial<Parameters<typeof NotifyComposeDialog>[0]> = {}) {
  const onMsg = vi.fn();
  const onClose = vi.fn();
  render(<NotifyComposeDialog customers={CUSTOMERS} onMsg={onMsg} onClose={onClose} {...props} />);
  return { onMsg, onClose };
}

describe('NotifyComposeDialog', () => {
  it('默认广播态:无顾客选择器;定向态切出选择器(Radix 空值两律:占位非选项)', async () => {
    renderDialog();
    expect(screen.queryByRole('combobox', { name: '选择顾客' })).not.toBeInTheDocument();
    await selectRadixOption('发送范围', '定向单客');
    expect(screen.getByRole('combobox', { name: '选择顾客' })).toBeInTheDocument();
  });

  it('单发锁定模式(lockedCustomer):范围恒定向、无范围选择器与顾客选择器', () => {
    renderDialog({ lockedCustomer: { id: 'CUST-8801', name: '张伟' } });
    expect(screen.getByText(/定向单客:张伟/)).toBeInTheDocument();
    expect(screen.queryByRole('combobox', { name: '发送范围' })).not.toBeInTheDocument();
    expect(screen.queryByRole('combobox', { name: '选择顾客' })).not.toBeInTheDocument();
  });

  it('单发锁定模式提交映射 targetType/customerId(effCustomerId 合成,选择器 state 不参与)', async () => {
    mocks.send.mockResolvedValue({ success: true });
    const { onMsg, onClose } = renderDialog({ lockedCustomer: { id: 'CUST-8801', name: '张伟' } });
    fireEvent.change(screen.getByLabelText('标题(必填,≤50 字)'), { target: { value: 'E2E 通知标题' } });
    fireEvent.change(screen.getByLabelText('正文(必填,≤500 字)'), { target: { value: '正文内容' } });
    fireEvent.click(screen.getByRole('button', { name: '发送' }));
    await waitFor(() => expect(mocks.send).toHaveBeenCalledTimes(1));
    expect(mocks.send).toHaveBeenCalledWith({
      targetType: 'customer',
      customerId: 'CUST-8801',
      title: 'E2E 通知标题',
      body: '正文内容',
    });
    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(onMsg).toHaveBeenCalledWith(expect.stringContaining('张伟'));
  });

  it('频控业务错误(success=false)文案留窗内、窗不关(FormDialogShell 契约)', async () => {
    mocks.send.mockResolvedValue({ success: false, message: '今日广播已达上限(20 条),请明日再试' });
    const { onClose } = renderDialog();
    fireEvent.change(screen.getByLabelText('标题(必填,≤50 字)'), { target: { value: 'E2E 广播' } });
    fireEvent.change(screen.getByLabelText('正文(必填,≤500 字)'), { target: { value: '正文' } });
    fireEvent.click(screen.getByRole('button', { name: '发送' }));
    expect(await screen.findByText(/今日广播已达上限/)).toBeInTheDocument();
    expect(onClose).not.toHaveBeenCalled();
  });
});
