import { type ClassValue, clsx } from 'clsx';
import { twMerge } from 'tailwind-merge';

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

// 卡片金额统一口径(shared-ui.md §2 / merchant-admin.md §1.4 同律):有限数值
// 才 toFixed(2);null/undefined/坏值/NaN/Infinity 一律诚实「—」,绝不兜底
// '0.00'(缺金额渲染成假 ¥0.00 是规则点名必挡的事故形态)。
export function formatAmount(val: unknown): string {
  if (typeof val === 'number') {
    return Number.isFinite(val) ? val.toFixed(2) : '—';
  }
  if (typeof val === 'string') {
    const num = Number.parseFloat(val.replace(/[^0-9.-]/g, ''));
    return Number.isNaN(num) ? '—' : num.toFixed(2);
  }
  return '—';
}
