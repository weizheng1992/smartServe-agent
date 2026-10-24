import { describe, expect, it } from 'vitest';
import { usageBadgeText } from './usageBadge';

// debug 角标文案单点(docs/ai-usage-panel.md P1):脏数据诚实 null,不渲染
describe('usageBadgeText', () => {
  it('亚秒延迟用 ms,超秒用一位小数 s', () => {
    expect(usageBadgeText({ totalTokens: 0, latencyMs: 124, turnPath: 'greeting' })).toBe('⚡ 124ms · 0 tok · greeting');
    expect(usageBadgeText({ totalTokens: 1523, latencyMs: 1523, turnPath: 'deep_path' })).toBe(
      '⚡ 1.5s · 1,523 tok · deep_path',
    );
  });

  it('无路径与空 usage 诚实降级', () => {
    expect(usageBadgeText({ totalTokens: 45, latencyMs: 800 })).toBe('⚡ 800ms · 45 tok');
    expect(usageBadgeText(null)).toBeNull();
    expect(usageBadgeText(undefined)).toBeNull();
  });

  it('字段类型异常不渲染(防后端形状漂移炸 UI)', () => {
    expect(usageBadgeText({ totalTokens: NaN, latencyMs: 100 })).toBeNull();
    // @ts-expect-error 脏形状探针
    expect(usageBadgeText({ latencyMs: 100 })).toBeNull();
  });
});
