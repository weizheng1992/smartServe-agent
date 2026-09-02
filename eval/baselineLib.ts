import { existsSync, readFileSync, writeFileSync } from 'node:fs';
import { basename, resolve } from 'node:path';

export const REPO_ROOT = resolve(__dirname, '..');
export const BASELINE_DIR = resolve(__dirname, 'baselines');

export interface SuiteDef {
  name: 'unified' | 'planner' | 'classify';
  config: string;
}

export const SUITES: SuiteDef[] = [
  { name: 'unified', config: 'eval/promptfooconfig.yaml' },
  { name: 'planner', config: 'eval/promptfoo.planner.yaml' },
  { name: 'classify', config: 'eval/promptfoo.classify.yaml' },
];

export interface ScorerAggregate {
  count: number;
  pass: number;
  fail: number;
  meanScore: number;
}

export interface SuiteSummary {
  total: number;
  pass: number;
  fail: number;
  errors: number;
  meanScore: number;
  scorers: Record<string, ScorerAggregate>;
}

export interface BaselineCase {
  description: string;
  success: boolean;
  score: number;
}

export interface SuiteBaseline {
  suite: string;
  pinnedAt: string;
  gitSha: string;
  config: { path: string; sha256: string };
  promptfooVersion: string;
  summary: SuiteSummary;
  cases: BaselineCase[];
}

export interface LatestIndex {
  pinnedAt: string;
  gitSha: string;
  suites: Record<string, SuiteSummary>;
}

interface PromptfooAssertion {
  type?: string;
  value?: unknown;
}

interface PromptfooGradingResult {
  pass?: boolean;
  score?: number;
  assertion?: PromptfooAssertion | null;
  componentResults?: PromptfooGradingResult[];
}

interface PromptfooResult {
  testIdx: number;
  description?: string;
  success: boolean;
  score: number;
  error?: string | null;
  gradingResult?: PromptfooGradingResult | null;
}

interface PromptfooSummary {
  version?: number;
  stats?: { successes?: number; failures?: number; errors?: number };
  results: PromptfooResult[];
}

export function sha256File(filePath: string): string {
  return new Bun.CryptoHasher('sha256').update(readFileSync(filePath)).digest('hex');
}

export function gitSha(): string {
  const res = Bun.spawnSync(['git', 'rev-parse', 'HEAD'], { cwd: REPO_ROOT });
  if (res.exitCode !== 0 || !res.stdout) return 'unknown';
  return res.stdout.toString().trim();
}

export function promptfooVersion(): string {
  const pkgPath = resolve(REPO_ROOT, 'node_modules/promptfoo/package.json');
  if (!existsSync(pkgPath)) return 'unknown';
  try {
    return JSON.parse(readFileSync(pkgPath, 'utf-8')).version || 'unknown';
  } catch {
    return 'unknown';
  }
}

export function baselinePath(suiteName: string): string {
  return resolve(BASELINE_DIR, `${suiteName}.json`);
}

export function readBaseline(suiteName: string): SuiteBaseline | null {
  const p = baselinePath(suiteName);
  if (!existsSync(p)) return null;
  return JSON.parse(readFileSync(p, 'utf-8')) as SuiteBaseline;
}

export function writeJson(filePath: string, data: unknown): void {
  writeFileSync(filePath, `${JSON.stringify(data, null, 2)}\n`);
}

export function runPromptfooSuite(suite: SuiteDef, outputFilePath: string): PromptfooSummary {
  const res = Bun.spawnSync(
    ['bunx', 'promptfoo', 'eval', '-c', suite.config, '-o', outputFilePath, '--no-write', '--no-cache', '--no-table'],
    { cwd: REPO_ROOT, stdout: 'inherit', stderr: 'inherit' },
  );
  if (res.exitCode !== 0) {
    throw new Error(`promptfoo eval 执行失败 (exit ${res.exitCode}): ${suite.name} (${suite.config})`);
  }
  if (!existsSync(outputFilePath)) {
    throw new Error(`promptfoo 未产出结果文件: ${outputFilePath}`);
  }
  const raw = JSON.parse(readFileSync(outputFilePath, 'utf-8')) as PromptfooSummary;
  if (!Array.isArray(raw.results)) {
    throw new Error(`promptfoo 结果文件缺少 results 数组: ${outputFilePath}`);
  }
  return raw;
}

function scorerKey(grading: PromptfooGradingResult): string {
  const value = grading.assertion?.value;
  if (typeof value === 'string' && value.length > 0) {
    return basename(value.split('?')[0]);
  }
  return grading.assertion?.type || 'unknown';
}

function collectGradingResults(grading: PromptfooGradingResult | null | undefined): PromptfooGradingResult[] {
  if (!grading) return [];
  if (Array.isArray(grading.componentResults) && grading.componentResults.length > 0) {
    return grading.componentResults;
  }
  return [grading];
}

export function summarizeSuite(raw: PromptfooSummary): SuiteSummary {
  const results = raw.results;
  const total = results.length;
  const pass = results.filter((r) => r.success).length;
  const fail = total - pass;
  const errors = raw.stats?.errors ?? results.filter((r) => typeof r.error === 'string' && r.error.length > 0).length;
  const meanScore = total > 0 ? results.reduce((acc, r) => acc + (r.score ?? 0), 0) / total : 0;

  const scorers: Record<string, ScorerAggregate> = {};
  const scorerSums: Record<string, number> = {};
  for (const result of results) {
    for (const grading of collectGradingResults(result.gradingResult)) {
      const key = scorerKey(grading);
      if (!scorers[key]) {
        scorers[key] = { count: 0, pass: 0, fail: 0, meanScore: 0 };
      }
      const agg = scorers[key];
      agg.count += 1;
      if (grading.pass) {
        agg.pass += 1;
      } else {
        agg.fail += 1;
      }
      scorerSums[key] = (scorerSums[key] ?? 0) + (grading.score ?? 0);
    }
  }
  for (const key of Object.keys(scorers)) {
    scorers[key].meanScore = scorerSums[key] / Math.max(scorers[key].count, 1);
  }

  return { total, pass, fail, errors, meanScore, scorers };
}

export function extractCases(raw: PromptfooSummary): BaselineCase[] {
  return raw.results.map((r) => ({
    description: r.description || `#${r.testIdx}`,
    success: r.success,
    score: r.score ?? 0,
  }));
}
