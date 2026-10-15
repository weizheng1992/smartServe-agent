// 全站金额呈现单点(2026-10-15 快修起头;候选③「数据诚实律模块化」的 fmtMoney 首砖):
// 缺值/坏值诚实「—」—— 注意 Number(null) === 0 必须先挡空值,否则缺金额
// 渲染成假 ¥0.00。调用形:`¥{fmtMoney(row.total_amount)}`。
export function fmtMoney(v: unknown): string {
  if (v === null || v === undefined || v === '') return '—';
  const n = Number(v);
  return Number.isFinite(n) ? n.toFixed(2) : '—';
}
