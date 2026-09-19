import '@testing-library/jest-dom/vitest';
import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { AskInputBar } from './ask-input-bar';

describe('AskInputBar', () => {
  it('输入 + 发送:回调收到的文本已 trim,输入框清空', () => {
    const onAsk = vi.fn();
    render(<AskInputBar busy={false} onAsk={onAsk} onGenReport={() => {}} reportMsg="" roleName="finance_owner" />);
    const input = screen.getByPlaceholderText(/问点什么/);
    fireEvent.change(input, { target: { value: '  近 30 天 GMV 趋势  ' } });
    fireEvent.click(screen.getByRole('button', { name: '发送' }));
    expect(onAsk).toHaveBeenCalledWith('近 30 天 GMV 趋势');
    expect(input).toHaveValue('');
  });

  it('Enter 键提交', () => {
    const onAsk = vi.fn();
    render(<AskInputBar busy={false} onAsk={onAsk} onGenReport={() => {}} reportMsg="" roleName="" />);
    const input = screen.getByPlaceholderText(/问点什么/);
    fireEvent.change(input, { target: { value: '会话量多少' } });
    fireEvent.keyDown(input, { key: 'Enter' });
    expect(onAsk).toHaveBeenCalledWith('会话量多少');
  });

  it('busy 时发送禁用且不触发回调;生成报告仍可用', () => {
    const onAsk = vi.fn();
    const onGenReport = vi.fn();
    render(<AskInputBar busy onAsk={onAsk} onGenReport={onGenReport} reportMsg="" roleName="" />);
    const send = screen.getByRole('button', { name: '发送' });
    expect(send).toBeDisabled();
    fireEvent.click(send);
    expect(onAsk).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: '生成报告' }));
    expect(onGenReport).toHaveBeenCalled();
  });

  it('空输入直接点发送不触发回调', () => {
    const onAsk = vi.fn();
    render(<AskInputBar busy={false} onAsk={onAsk} onGenReport={() => {}} reportMsg="" roleName="" />);
    fireEvent.click(screen.getByRole('button', { name: '发送' }));
    expect(onAsk).not.toHaveBeenCalled();
  });
});
