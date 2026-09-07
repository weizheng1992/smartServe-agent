import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: '.',
  testMatch: ['apps/**/e2e/**/*.e2e.ts'],
  // 熔断 spec 由 playwright.breaker.config.ts 独占运行(独立网关注入死 LLM);
  // .claude/worktrees 是 agent 会话的临时检出副本,非套件成员(曾整目录被收集成幽灵重复用例)
  testIgnore: [/circuit-breaker\.e2e\.ts$/, /[\\/]\.claude[\\/]worktrees[\\/]/],
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: 'html',
  use: {
    baseURL: 'http://localhost:3000',
    trace: 'on-first-retry',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
    {
      name: 'firefox',
      use: { ...devices['Desktop Firefox'] },
    },
    {
      name: 'webkit',
      use: { ...devices['Desktop Safari'] },
    },
  ],
  // 后端/DB 由 globalSetup 幂等就绪(wayfinder 004):此前只拉前端,契约依赖手工步骤
  globalSetup: './e2e/globalSetup.ts',
  webServer: [
    {
      command: 'cd services/gateway-py && uv run --env-file ../../.env uvicorn gateway_py.main:app --host 127.0.0.1 --port 4000',
      url: 'http://localhost:4000/api/health',
      reuseExistingServer: !process.env.CI,
      timeout: 120 * 1000,
    },
    {
      command: 'bun run dev:web',
      url: 'http://localhost:3000',
      reuseExistingServer: !process.env.CI,
      timeout: 120 * 1000,
    },
    {
      command: 'bun run dev:admin',
      url: 'http://localhost:3001',
      reuseExistingServer: !process.env.CI,
      timeout: 120 * 1000,
    },
    {
      // 商户门户(3005):基线 webServer `bun run dev` 经 turbo --filter=merchant
      // 一并拉起过,显式数组化后必须保留,否则 merchant 三个 spec 连接被拒
      command: 'bun run dev:merchant',
      url: 'http://localhost:3005',
      reuseExistingServer: !process.env.CI,
      timeout: 120 * 1000,
    },
  ],
});
