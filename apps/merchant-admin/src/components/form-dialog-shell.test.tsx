import '@testing-library/jest-dom/vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { useState } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { FormDialogShell } from './form-dialog-shell';

// 壳契约钉(候选④):busy 防重复提交(此前全仓 12/13 弹窗零覆盖)、成功自动
// 关窗、失败文案留窗内不关窗。此前这些语义只有 promo-dialog 一家有。

function Harness({ onSubmit }: { onSubmit: () => Promise<string | null> }) {
  const [closed, setClosed] = useState(false);
  if (closed) return <div data-testid="closed">已关闭</div>;
  return (
    <FormDialogShell title="测试弹窗" submitLabel="提交" onClose={() => setClosed(true)} onSubmit={onSubmit}>
      <input aria-label="字段" defaultValue="v1" />
    </FormDialogShell>
  );
}

describe('FormDialogShell(chrome/footer/busy 状态机单点)', () => {
  it('成功(返回 null):自动关窗', async () => {
    const onClose = vi.fn();
    render(
      <FormDialogShell title="t" submitLabel="提交" onClose={onClose} onSubmit={async () => null}>
        <div>body</div>
      </FormDialogShell>,
    );
    fireEvent.click(screen.getByRole('button', { name: '提交' }));
    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
  });

  it('失败(返回文案):留窗内不关窗,可再提交', async () => {
    let fail = true;
    const onClose = vi.fn();
    render(
      <FormDialogShell
        title="t"
        submitLabel="提交"
        onClose={onClose}
        onSubmit={async () => {
          if (fail) {
            fail = false;
            return '名称已被占用';
          }
          return null;
        }}
      >
        <div>body</div>
      </FormDialogShell>,
    );
    fireEvent.click(screen.getByRole('button', { name: '提交' }));
    await waitFor(() => expect(screen.getByText('名称已被占用')).toBeInTheDocument());
    expect(onClose).not.toHaveBeenCalled(); // 窗不关,用户可改后重试
    fireEvent.click(screen.getByRole('button', { name: '提交' }));
    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1)); // 二次成功
    expect(screen.queryByText('名称已被占用')).not.toBeInTheDocument();
  });

  it('busy 闸:提交在途禁提交键(防双 PATCH;在途一次只发一个请求)', async () => {
    let release!: () => void;
    let calls = 0;
    const onSubmit = vi.fn(
      () =>
        new Promise<string | null>((r) => {
          calls += 1;
          if (calls === 1) {
            release = () => r(null);
            return;
          }
          r(null);
        }),
    );
    const onClose = vi.fn();
    render(
      <FormDialogShell title="t" submitLabel="提交" onClose={onClose} onSubmit={onSubmit}>
        <div>body</div>
      </FormDialogShell>,
    );
    fireEvent.click(screen.getByRole('button', { name: '提交' }));
    expect(screen.getByRole('button', { name: '提交' })).toBeDisabled(); // 在途闸
    release();
    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
    expect(onSubmit).toHaveBeenCalledTimes(1); // 双击不产生第二笔
  });

  it('submitDisabled:与 busy 独立,禁用态不被壳覆盖', () => {
    render(
      <FormDialogShell title="t" submitLabel="提交" submitDisabled onClose={() => {}} onSubmit={async () => null}>
        <div>body</div>
      </FormDialogShell>,
    );
    expect(screen.getByRole('button', { name: '提交' })).toBeDisabled();
  });
});
