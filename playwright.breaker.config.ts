import { defineConfig, devices } from '@playwright/test';

/**
 * 熔断器专用配置(wayfinder 004):独立网关(4001)+ 独立前端(3010)。
 *
 * 环境注入(进程 env 优先于 uv --env-file,uv 不覆写已设变量):
 *   AI_BASE_URL=http://127.0.0.1:59998  死端口,连接即拒(注入上游故障)
 *   LLM_CIRCUIT_MAX_FAILURES=1          首次失败即熔断 OPEN
 *   LLM_RETRY_MAX_ATTEMPTS=1            单次重试后快速放弃
 *   LLM_RETRY_INITIAL_DELAY_MS=50       退避不拖长用例
 *   LLM_TIMEOUT_SECONDS=5               连接拒收兜底
 * 前端经 apps/web/vite.config.ts 的 E2E_GATEWAY_TARGET 把 /api 代理到 4001。
 */
export default defineConfig({
  testDir: '.',
  testMatch: [/circuit-breaker\.e2e\.ts$/],
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: 0,
  workers: 1,
  reporter: 'list',
  use: {
    baseURL: 'http://localhost:3010',
    trace: 'on-first-retry',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
  globalSetup: './e2e/globalSetup.ts',
  webServer: [
    {
      command:
        'cd services/gateway-py && AI_BASE_URL=http://127.0.0.1:59998 LLM_CIRCUIT_MAX_FAILURES=1 LLM_RETRY_MAX_ATTEMPTS=1 LLM_RETRY_INITIAL_DELAY_MS=50 LLM_TIMEOUT_SECONDS=5 uv run --env-file ../../.env uvicorn gateway_py.main:app --host 127.0.0.1 --port 4001',
      url: 'http://localhost:4001/api/health',
      reuseExistingServer: false,
      timeout: 120 * 1000,
    },
    {
      command: 'cd apps/web && E2E_GATEWAY_TARGET=http://localhost:4001 bun run dev --port 3010 --strictPort',
      url: 'http://localhost:3010',
      reuseExistingServer: false,
      timeout: 120 * 1000,
    },
  ],
});
