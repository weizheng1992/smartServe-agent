// 商城端 AI 回复 debug 角标(docs/ai-usage-panel.md P1,共识 Q11a):
// ?debug=usage 开启后每条 AI 回复下方小字「⚡耗时 · tok · 路径」—— 仅本机
// 渲染、仅当轮(SSE/POST 携带 usage 的回复)生效,顾客默认不可见,
// 历史消息不回填(历史接口不动)。
export interface TurnUsage {
  totalTokens: number;
  latencyMs: number;
  turnPath?: string | null;
}

export function usageBadgeText(usage: TurnUsage | null | undefined): string | null {
  if (!usage) return null;
  // Number.isFinite 同挡 undefined 与 NaN(NaN 是 number 类型,typeof 挡不住)
  if (!Number.isFinite(usage.latencyMs) || !Number.isFinite(usage.totalTokens)) return null;
  const latency = usage.latencyMs >= 1000 ? `${(usage.latencyMs / 1000).toFixed(1)}s` : `${usage.latencyMs}ms`;
  const path = usage.turnPath ? ` · ${usage.turnPath}` : '';
  return `⚡ ${latency} · ${usage.totalTokens.toLocaleString('zh-CN')} tok${path}`;
}
