import { defineConfig, devices } from '@playwright/test';

/**
 * 修复回归专用最小配置(2026-09-13 admin 十模块点击测试修复验证):
 * 复用已在运行的 3001(admin)/4000(网关),不执行 globalSetup 的重播种链,
 * 仅 Chromium 单浏览器,避免对本机开发库做任何种子写入。
 */
export default defineConfig({
  testDir: '../apps/admin/e2e',
  testMatch: /\.e2e\.ts$/,
  testIgnore: /circuit-breaker\.e2e\.ts$/,
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [['list']],
  use: {
    baseURL: 'http://localhost:3001',
    trace: 'off',
    viewport: { width: 1600, height: 1000 },
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
});
