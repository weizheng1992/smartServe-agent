// 诚实呈现助手:缺值/坏值一律「—」,严禁 Number(null)===0 冒充 ¥0.00 / Invalid Date
// (merchant-admin.md §1.4 同纪律;订单面统一消费,勿再内联复制)

export const fmtMoney = (v: unknown): string => {
  const n = Number(v);
  return v != null && v !== '' && Number.isFinite(n) ? n.toFixed(2) : '—';
};

export const fmtDate = (v: unknown): string => {
  if (v == null || v === '') return '—';
  const d = new Date(v as string | number);
  return Number.isNaN(d.getTime()) ? '—' : d.toLocaleString();
};

export const toNum = (v: unknown): number | null => {
  const n = Number(v);
  return v != null && v !== '' && Number.isFinite(n) ? n : null;
};
