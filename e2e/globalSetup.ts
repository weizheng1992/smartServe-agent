import { execSync } from 'node:child_process';

import type { FullConfig } from '@playwright/test';

/**
 * E2E 全局前置(wayfinder 004):把"后端/DB 需手工就绪"的约定脚本化。
 *
 * 幂等链:核心容器(已在跑则秒过)→ Alembic schema → 三路种子(engine/三方/商户)。
 * 种子侧 ON CONFLICT DO UPDATE 会重绑种子账号归属并重置 ORD-ECO-LARGE 的
 * 退款状态与送达日期,保证 HITL 审批流用例可重复执行。
 */
// playwright 以配置目录为 cwd 启动 globalSetup(根 package.json 非 ESM,勿用 import.meta)
const ROOT = process.cwd();

function run(command: string): void {
  console.log(`[E2E globalSetup] $ ${command}`);
  execSync(command, { cwd: ROOT, stdio: 'inherit', timeout: 300_000 });
}

export default async function globalSetup(_config: FullConfig): Promise<void> {
  console.log('[E2E globalSetup] 基础设施就绪检查开始…');
  try {
    run('bun run docker:up');
    run('bun run db:push');
    run('bun run db:seed');
  } catch (err) {
    throw new Error(
      `[E2E globalSetup] 基础设施链失败(docker:up → db:push → db:seed)。` +
        `请手动执行上述三步定位:docker 是否运行、.env 的 DATABASE_URL/REDIS_URL 是否可达。原始错误:${err}`,
    );
  }
  console.log('[E2E globalSetup] 基础设施就绪 ✅');
}
