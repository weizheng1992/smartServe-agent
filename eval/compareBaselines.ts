import { existsSync, mkdirSync, readFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { resolve } from 'node:path';
import {
  type BaselineCase,
  SUITES,
  type SuiteBaseline,
  type SuiteSummary,
  baselinePath,
  extractCases,
  readBaseline,
  runPromptfooSuite,
  summarizeSuite,
} from './baselineLib';

const SCORE_EPSILON = 1e-9;

interface SuiteComparison {
  suite: string;
  baseline: SuiteBaseline;
  current: SuiteSummary;
  currentCases: BaselineCase[];
  regressions: string[];
}

function readRawSummary(filePath: string) {
  if (!existsSync(filePath)) {
    throw new Error(`结果文件不存在: ${filePath}`);
  }
  const raw = JSON.parse(readFileSync(filePath, 'utf-8'));
  if (!Array.isArray(raw.results)) {
    throw new Error(`结果文件缺少 results 数组: ${filePath}`);
  }
  return raw;
}

function compareSuite(baseline: SuiteBaseline, current: SuiteSummary, currentCases: BaselineCase[]): string[] {
  const regressions: string[] = [];
  const { summary: base } = baseline;

  if (current.total < base.total) {
    regressions.push(`用例总数下降: ${base.total} -> ${current.total} (有用例被删除或未执行)`);
  }
  if (current.pass < base.pass) {
    regressions.push(`通过数下降: ${base.pass} -> ${current.pass}`);
  }
  if (current.fail > base.fail) {
    regressions.push(`失败数上升: ${base.fail} -> ${current.fail}`);
  }
  if (current.errors > base.errors) {
    regressions.push(`错误数上升: ${base.errors} -> ${current.errors}`);
  }
  if (current.meanScore < base.meanScore - SCORE_EPSILON) {
    regressions.push(`整体均分下降: ${base.meanScore.toFixed(4)} -> ${current.meanScore.toFixed(4)}`);
  }

  for (const [name, baseAgg] of Object.entries(base.scorers)) {
    const currAgg = current.scorers[name];
    if (!currAgg) {
      regressions.push(`scorer [${name}] 在本次结果中消失 (基线: ${baseAgg.count} 次)`);
      continue;
    }
    if (currAgg.meanScore < baseAgg.meanScore - SCORE_EPSILON) {
      regressions.push(`scorer [${name}] 均分下降: ${baseAgg.meanScore.toFixed(4)} -> ${currAgg.meanScore.toFixed(4)}`);
    }
    if (currAgg.pass < baseAgg.pass) {
      regressions.push(`scorer [${name}] 通过数下降: ${baseAgg.pass} -> ${currAgg.pass}`);
    }
  }

  const currentByDescription = new Map(currentCases.map((c) => [c.description, c]));
  for (const baseCase of baseline.cases) {
    if (!baseCase.success) continue;
    const curr = currentByDescription.get(baseCase.description);
    if (!curr) {
      regressions.push(`基线中通过的用例在本次结果中缺失: "${baseCase.description}"`);
    } else if (!curr.success) {
      regressions.push(`用例由通过转为失败: "${baseCase.description}"`);
    }
  }

  return regressions;
}

async function compareBaselines() {
  const resultsDirIdx = process.argv.indexOf('--results-dir');
  const resultsDir = resultsDirIdx >= 0 ? process.argv[resultsDirIdx + 1] : undefined;

  console.log('================================================================');
  console.log('🔍 Promptfoo 基线对比 (Baseline Comparison)');
  console.log(`结果来源: ${resultsDir ? `--results-dir ${resultsDir}` : '现场重跑三套评测'}`);
  console.log('================================================================\n');

  const missing = SUITES.filter((s) => !existsSync(baselinePath(s.name)));
  if (missing.length > 0) {
    console.error('❌ 以下基线缺失,请先执行: bun run test:prompt:pin');
    for (const s of missing) {
      console.error(`   - ${baselinePath(s.name)}`);
    }
    process.exit(1);
  }

  const workDir = resolve(tmpdir(), `promptfoo-compare-${Date.now()}`);
  if (!resultsDir) {
    mkdirSync(workDir, { recursive: true });
  }

  const comparisons: SuiteComparison[] = [];
  for (const suite of SUITES) {
    const baseline = readBaseline(suite.name);
    if (!baseline) continue;

    console.log(`▶ 获取 [${suite.name}] 当前结果 ...`);
    const raw = resultsDir
      ? readRawSummary(resolve(resultsDir, `${suite.name}.json`))
      : runPromptfooSuite(suite, resolve(workDir, `${suite.name}.json`));

    const current = summarizeSuite(raw);
    const currentCases = extractCases(raw);
    const regressions = compareSuite(baseline, current, currentCases);
    comparisons.push({ suite: suite.name, baseline, current, currentCases, regressions });
  }

  console.log('\n================================================================');
  console.log('📊 对比汇总');
  console.log('================================================================');
  console.log(
    `${'套件'.padEnd(10)}${'基线 pass/fail'.padEnd(18)}${'当前 pass/fail'.padEnd(18)}${'基线均分'.padEnd(12)}${'当前均分'.padEnd(12)}判定`,
  );
  console.log('-'.repeat(80));

  let anyRegression = false;
  for (const c of comparisons) {
    const bad = c.regressions.length > 0;
    anyRegression = anyRegression || bad;
    console.log(
      `${c.suite.padEnd(10)}${`${c.baseline.summary.pass}/${c.baseline.summary.fail}`.padEnd(18)}${`${c.current.pass}/${c.current.fail}`.padEnd(18)}${c.baseline.summary.meanScore.toFixed(4).padEnd(12)}${c.current.meanScore.toFixed(4).padEnd(12)}${bad ? '❌ 回归' : '✅ 对齐'}`,
    );
    for (const r of c.regressions) {
      console.log(`    - ${r}`);
    }
  }

  console.log('-'.repeat(80));
  if (anyRegression) {
    console.log('❌ 存在回归: 任一 pass 下降 / fail 上升 / scorer 均分下降 / 基线通过用例转失败,均不达标。');
    process.exit(1);
  } else {
    console.log(`✅ 全部 ${comparisons.length} 套与基线对齐,无回归。`);
  }
}

compareBaselines().catch((err) => {
  console.error('Fatal baseline comparison error:', err);
  process.exit(1);
});
