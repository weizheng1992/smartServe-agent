import { defineConfig, devices } from '@playwright/test';

/** 商户运营台审计专用最小配置(admin-readiness 04):baseURL 3005,仅 Chromium。 */
export default defineConfig({
  testDir: '../apps/merchant/e2e',
  testMatch: /.*\.e2e\.ts$/,
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [['list']],
  use: {
    baseURL: 'http://localhost:3005',
    trace: 'off',
    viewport: { width: 1600, height: 1000 },
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
});
