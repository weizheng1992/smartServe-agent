import { defineConfig, devices } from '@playwright/test';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

// 消息推送 e2e 专属配置(mall-notifications 06):baseURL 3007 = 私有 vite
// (GATEWAY_URL 代理私有网关 4100),与 dev 的 3005/4000 完全隔离 —— dev 网关
// 跑的是旧代码,重启属部署动作不归本册;webServer url 已响应即复用跳过
// (Playwright 内建语义),故先起 4100 再跑本册也能与已有私有实例共存。
// 运行:bunx playwright test --config apps/merchant/e2e/notifications.config.ts
// (webServer cwd 实测相对本配置文件目录解析,一律绝对路径,防 ENOENT。)

const E2E_DIR = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(E2E_DIR, '../../..');

export default defineConfig({
  // testDir 省略 = 配置文件所在目录(e2e/);显式 testMatch 防默认 spec/test
  // 规则漏掉 .e2e.ts 命名。webServer cwd 相对进程 cwd —— 本册须自仓库根运行。
  testMatch: /notifications\.e2e\.ts/,
  timeout: 60_000,
  reporter: 'list',
  use: {
    baseURL: 'http://localhost:3007',
    trace: 'retain-on-failure',
    ...devices['Desktop Chrome'],
  },
  env: {
    AI_QUOTA_GATE: '0',
  },
  webServer: [
    {
      command:
        'ENGINE_SCHEDULER_ENABLED=0 uv run --env-file ../../.env uvicorn gateway_py.main:app --host 127.0.0.1 --port 4100',
      url: 'http://127.0.0.1:4100/api/health',
      cwd: resolve(ROOT, 'services/gateway-py'),
      reuseExistingServer: true,
      timeout: 60_000,
    },
    {
      command: `GATEWAY_URL=http://127.0.0.1:4100 ${resolve(ROOT, 'node_modules/.bin/vite')} --port 3007 --strictPort`,
      url: 'http://localhost:3007',
      cwd: resolve(ROOT, 'apps/merchant'),
      reuseExistingServer: true,
      timeout: 60_000,
    },
  ],
});
