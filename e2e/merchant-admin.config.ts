import { defineConfig, devices } from '@playwright/test';

/**
 * merchant-admin E2E(data agent 面;复用运行中的 3006 前端 + 4000 网关)。
 * 仅 Chromium;不播种;对话断言走真实后端(网关须在跑)。
 */
export default defineConfig({
  testDir: '../apps/merchant-admin/e2e',
  testMatch: /.*\.e2e\.ts$/,
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [['list']],
  use: {
    baseURL: 'http://localhost:3006',
    trace: 'off',
    viewport: { width: 1600, height: 1000 },
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
});
