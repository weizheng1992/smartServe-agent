/** 真实评测记录 + 入库(wayfinder 005)。
 *
 * 依次跑三套 promptfoo 套件(unified / planner / classify)落盘到
 * eval/.records/<suite>.json,再调 engine-py 导入 CLI 把结果写入
 * eval_runs / eval_results + eval_run_records 展示汇总行(admin 评测页)。
 * 用法:bun run test:prompt:record
 */
import { mkdirSync } from 'node:fs';
import { resolve } from 'node:path';
import { REPO_ROOT, SUITES, runPromptfooSuite } from './baselineLib';

const RECORD_DIR = resolve(REPO_ROOT, 'eval/.records');

function main(): never {
  mkdirSync(RECORD_DIR, { recursive: true });
  for (const suite of SUITES) {
    console.log(`\n▶ 记录套件 ${suite.name} (${suite.config})`);
    runPromptfooSuite(suite, resolve(RECORD_DIR, `${suite.name}.json`));
  }

  console.log('\n▶ 导入数据库(eval_runs / eval_results / eval_run_records)');
  const res = Bun.spawnSync(
    ['uv', 'run', 'python', '-m', 'engine_py.evals.promptfoo_import', '../../eval/.records'],
    { cwd: resolve(REPO_ROOT, 'services/engine-py'), stdout: 'inherit', stderr: 'inherit' },
  );
  process.exit(res.exitCode ?? 1);
}

main();
