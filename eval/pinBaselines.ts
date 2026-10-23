import { existsSync, mkdirSync, readFileSync } from 'node:fs';
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
  fingerprintDatasets,
  gitSha,
  promptfooVersion,
  runPromptfooSuite,
  sha256File,
  summarizeSuite,
  writeJson,
} from './baselineLib';

async function pinBaselines() {
  const update = process.argv.includes('--update');
  // 位置参数套件过滤(可选):`bun run test:prompt:pin -- rag` 只钉 rag 册 ——
  // 无 LLM 册可高频重钉,不必陪跑 LLM 长跑册;多个位置参数 = 白名单集合;
  // 拼错的名字响亮 exit(1)
  const onlyArgs = process.argv.slice(2).filter((a) => a !== '--update' && !a.endsWith('.ts'));
  const known = new Set(SUITES.map((s) => s.name));
  const unknown = onlyArgs.filter((a) => !known.has(a));
  if (unknown.length > 0) {
    console.error(`❌ 未知套件: ${unknown.join(', ')}(可选: ${SUITES.map((s) => s.name).join(', ')})`);
    process.exit(1);
  }
  const targetSuites = onlyArgs.length > 0 ? SUITES.filter((s) => onlyArgs.includes(s.name)) : SUITES;

  console.log('================================================================');
  console.log('📌 Promptfoo 基线钉死 (Baseline Pinning)');
  console.log(
    `模式: ${update ? '--update (允许覆盖已有基线)' : '首次钉定 (已存在则拒绝)'} | 套件: ${targetSuites.map((s) => s.name).join(', ')}`,
  );
  console.log('================================================================\n');

  // 先做存在性预检,避免跑了评测才发现基线已存在
  if (!update) {
    const existing = targetSuites.filter((s) => existsSync(baselinePath(s.name)));
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
  // 部分钉定合并:latest.json 保留未重钉套件的历史摘要(仅覆盖本次目标套件),
  // 否则 `pin -- rag` 会把 unified/planner/persona 的摘要从 latest 索引里抹掉。
  // 顶层 pinnedAt/gitSha 仅在**全量**钉定时刷新 —— 部分钉定把它们留在原值,
  // 诚实表达「索引顶层=最后一次全量钉定」(评审 S3-a2:混合钉定不得伪装单次)
  const latestPath = resolve(BASELINE_DIR, 'latest.json');
  const partial = targetSuites.length < SUITES.length;
  let index: LatestIndex = { pinnedAt, gitSha: sha, suites: {} };
  if (partial && existsSync(latestPath)) {
    try {
      index = JSON.parse(readFileSync(latestPath, 'utf-8')) as LatestIndex;
    } catch {
      // 损坏的 latest 按全新索引处理(目标套件摘要仍会写入)
    }
  }
  // 目标套件摘要由下方主循环以真实结果覆写进 index.suites

  for (const suite of targetSuites) {
    console.log(`\n▶ 运行套件 [${suite.name}] (${suite.config}) ...`);
    const outputFile = resolve(workDir, `${suite.name}.json`);
    const raw = runPromptfooSuite(suite, outputFile);

    const baseline: SuiteBaseline = {
      suite: suite.name,
      pinnedAt,
      gitSha: sha,
      config: { path: suite.config, sha256: sha256File(resolve(REPO_ROOT, suite.config)) },
      datasets: fingerprintDatasets(suite.config),
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
  console.log(`🏆 基线钉定完成: ${targetSuites.length} 套 | git ${sha.slice(0, 8)} | ${pinnedAt}`);
  console.log('请将 eval/baselines/ 一并提交,它是 Python engine 重写的等价性验收门禁。');
  console.log('================================================================');
}

pinBaselines().catch((err) => {
  console.error('Fatal baseline pinning error:', err);
  process.exit(1);
});
