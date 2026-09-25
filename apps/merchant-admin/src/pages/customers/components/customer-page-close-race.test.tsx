import '@testing-library/jest-dom/vitest';
import { setSession } from '@/lib/api';
import { gatewayUp, installLiveFetch, login } from '@/test/live-api';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import CustomersPage from '../index';

// 回归(ADR-0005 客户详情抽屉「关不掉」):
// load 依赖 detail + setDetail(每次 fetch 的新对象) → 抽屉开着时无限重取循环;
// 点「关闭」置 null 后,在途 load 的陈旧闭包又把 detail 设回对象 → 抽屉重开。
// 修复后:关闭后抽屉必须保持关闭(即使后续 fetch 继续返回)。

const d = gatewayUp ? describe : describe.skip;

beforeAll(() => {
  installLiveFetch();
});

afterEach(() => vi.unstubAllGlobals());

d('CustomersPage 详情抽屉关闭', () => {
  it('点详情打开 → 点关闭 → 抽屉关闭且保持关闭', async () => {
    const boss = await login('test@example.com');
    setSession(boss.token, boss.email);

    render(
      <MemoryRouter>
        <CustomersPage />
      </MemoryRouter>,
    );

    const detailBtn = await screen.findByRole('button', { name: '详情' }, { timeout: 8000 });
    fireEvent.click(detailBtn);
    const closeBtn = await screen.findByRole('button', { name: '关闭' }, { timeout: 8000 });
    fireEvent.click(closeBtn);

    // 关闭后立刻消失
    await waitFor(() => expect(screen.queryByRole('button', { name: '关闭' })).not.toBeInTheDocument());
    // 关键回归点:2.5 秒后仍保持关闭(陈旧在途 load 不得重新打开)
    await new Promise((r) => setTimeout(r, 2500));
    expect(screen.queryByRole('button', { name: '关闭' })).not.toBeInTheDocument();
  }, 20000);
});
