import { existsSync, mkdirSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { resolve } from 'node:path';
import {
  BASELINE_DIR,
  type LatestIndex,
  REPO_ROOT,
  SUITES,
  type SuiteBaseline,
  baselinePath,
  extractCases,
  gitSha,
  promptfooVersion,
  runPromptfooSuite,
  sha256File,
  summarizeSuite,
  writeJson,
} from './baselineLib';

async function pinBaselines() {
  const update = process.argv.includes('--update');

  console.log('================================================================');
  console.log('📌 Promptfoo 基线钉死 (Baseline Pinning)');
  console.log(`模式: ${update ? '--update (允许覆盖已有基线)' : '首次钉定 (已存在则拒绝)'}`);
  console.log('================================================================\n');

  // 先做存在性预检,避免跑了评测才发现基线已存在
  if (!update) {
    const existing = SUITES.filter((s) => existsSync(baselinePath(s.name)));
    if (existing.length > 0) {
      console.error('❌ 以下基线已存在,拒绝覆盖 (防止无意漂移):');
      for (const s of existing) {
        console.error(`   - ${baselinePath(s.name)}`);
      }
      console.error('\n如确属有意重新钉定,请使用: bun run test:prompt:pin -- --update');
      process.exit(1);
    }
  }

  mkdirSync(BASELINE_DIR, { recursive: true });
  const workDir = resolve(tmpdir(), `promptfoo-baseline-${Date.now()}`);
  mkdirSync(workDir, { recursive: true });

  const pinnedAt = new Date().toISOString();
  const sha = gitSha();
  const index: LatestIndex = { pinnedAt, gitSha: sha, suites: {} };

  for (const suite of SUITES) {
    console.log(`\n▶ 运行套件 [${suite.name}] (${suite.config}) ...`);
    const outputFile = resolve(workDir, `${suite.name}.json`);
    const raw = runPromptfooSuite(suite, outputFile);

    const baseline: SuiteBaseline = {
      suite: suite.name,
      pinnedAt,
      gitSha: sha,
      config: { path: suite.config, sha256: sha256File(resolve(REPO_ROOT, suite.config)) },
      promptfooVersion: promptfooVersion(),
      summary: summarizeSuite(raw),
      cases: extractCases(raw),
    };
    writeJson(baselinePath(suite.name), baseline);
    index.suites[suite.name] = baseline.summary;

    const { total, pass, fail, meanScore } = baseline.summary;
    console.log(
      `✅ 已钉定 [${suite.name}]: 总用例 ${total} | 通过 ${pass} | 失败 ${fail} | 均分 ${meanScore.toFixed(4)}`,
    );
  }

  writeJson(resolve(BASELINE_DIR, 'latest.json'), index);
  console.log('\n================================================================');
  console.log(`🏆 基线钉定完成: ${SUITES.length} 套 | git ${sha.slice(0, 8)} | ${pinnedAt}`);
  console.log('请将 eval/baselines/ 一并提交,它是 Python engine 重写的等价性验收门禁。');
  console.log('================================================================');
}

pinBaselines().catch((err) => {
  console.error('Fatal baseline pinning error:', err);
  process.exit(1);
});
