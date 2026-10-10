// 单浅色主题契约(2026-10-09 实弹):Tailwind v4 的 dark: 变体默认走
// @media (prefers-color-scheme: dark),OS 深色模式下散写的 dark:bg-* 半边翻色
// 而文字色不跟随 → 黑底黑字(owner-mappings 表格与 Dialog 涂黑事故)。
// 结构性闸在 ui globals.css 的 @custom-variant dark(类驱动,无 .dark 类恒惰性);
// 本测试钉源码面:ts/tsx 不出现 dark: 写法 —— 未来若真立暗色主题(token 级方案),
// 应连同本契约一起改,而不是绕过它。
// 只扫 ts/tsx:globals.css 的 @custom-variant 注释含 dark: 字样属合法存在。
import { existsSync, readFileSync, readdirSync, statSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

// 向上找 turbo.json 锚定仓库根(免疫 vitest/turbo 两种入口的 cwd 差异)
function findRepoRoot(start: string): string {
  let dir = start;
  for (;;) {
    if (existsSync(path.join(dir, 'turbo.json'))) return dir;
    const parent = path.dirname(dir);
    if (parent === dir) throw new Error(`turbo.json 不存在于任何祖先目录(起点 ${start})`);
    dir = parent;
  }
}

const REPO_ROOT = findRepoRoot(__dirname);
const SCAN_ROOTS = [path.join(REPO_ROOT, 'apps/merchant-admin/src'), path.join(REPO_ROOT, 'packages/ui/src')];
const EXTENSIONS = new Set(['.ts', '.tsx']);
// 本文件注释含 dark: 字样,自排除(否则自诉)
const SELF = path.resolve(__dirname, 'light-theme-contract.test.ts');

function* walkTsSources(dir: string): Generator<string> {
  for (const name of readdirSync(dir)) {
    const full = path.join(dir, name);
    const stat = statSync(full);
    if (stat.isDirectory()) yield* walkTsSources(full);
    else if (EXTENSIONS.has(path.extname(name))) yield full;
  }
}

describe('单浅色主题契约', () => {
  it('merchant-admin 与 ui 的 ts/tsx 源码零 dark: 变体(OS 深色模式不再能翻色)', () => {
    const offenders: string[] = [];
    for (const root of SCAN_ROOTS) {
      for (const file of walkTsSources(root)) {
        if (file === SELF) continue;
        const lines = readFileSync(file, 'utf8').split('\n');
        lines.forEach((line, i) => {
          if (line.includes('dark:')) offenders.push(`${path.relative(REPO_ROOT, file)}:${i + 1}: ${line.trim()}`);
        });
      }
    }
    expect(offenders).toEqual([]);
  });
});
