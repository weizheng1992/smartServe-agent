/**
 * merchant-admin 专属 Playwright 配置:复用运行中的 3006 前端 + 4000 网关
 * (真实 LLM 作答,不 mock)。跑法:
 *   bunx playwright test --config=apps/merchant-admin/e2e/merchant-admin.config.ts
 * 前置:bun run dev:merchant-admin(3006)+ 网关 4000(无则本配置代拉)。
 */
import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: '.',
  testMatch: ['*.e2e.ts'],
  fullyParallel: false,
  retries: 0,
  reporter: 'list',
  timeout: 180_000,
  use: {
    baseURL: 'http://localhost:3006',
    trace: 'on-first-retry',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: [
    {
      command: 'cd services/gateway-py && uv run --env-file ../../.env uvicorn gateway_py.main:app --host 127.0.0.1 --port 4000',
      url: 'http://localhost:4000/api/health',
      reuseExistingServer: true,
      timeout: 120 * 1000,
    },
    {
      command: 'bun run dev:merchant-admin',
      url: 'http://localhost:3006/',
      reuseExistingServer: true,
      timeout: 120 * 1000,
    },
  ],
});
