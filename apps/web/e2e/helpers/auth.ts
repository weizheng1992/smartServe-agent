import type { Page } from '@playwright/test';

/**
 * E2E 真实登录(走 /api/auth/login 完整链路,无 localStorage 旁路)。
 *
 * 凭证来自 engine 种子账号(engine_py.db.seed,E2E_ACCOUNT_PASSWORD 可覆写);
 * 前置(与既有约定一致,playwright webServer 只拉起前端):
 *   bun run docker:up && bun run db:push && bun run db:seed && bun run dev:server
 */
export const E2E_ACCOUNT_EMAIL = process.env.E2E_ACCOUNT_EMAIL ?? 'test@example.com';
export const E2E_ACCOUNT_PASSWORD = process.env.E2E_ACCOUNT_PASSWORD ?? 'agent-all-dev';

export async function loginViaUi(
  page: Page,
  email: string = E2E_ACCOUNT_EMAIL,
  password: string = E2E_ACCOUNT_PASSWORD,
): Promise<void> {
  await page.goto('/login');
  await page.locator('input[type="email"]').fill(email);
  await page.locator('input[type="password"]').fill(password);
  await page.locator('button[type="submit"]').click();
  await page.waitForURL('/');
}
