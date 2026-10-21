/**
 * 商户积分池呈现层纯函数单点(2026-10-21 用量配额闸,spec §5 admin 面)。
 * 校验/文案/格式化与组件分离:弹窗只做编排,规则在此可测(bun 册无 DOM)。
 */
import type { CreditTransaction } from '../../lib/api';
export type { CreditTransaction };

/**
 * 调整弹窗客户端轻校验(服务端同律双保险):返回错误文案,通过返回 null。
 * 服务端契约:reason 必填、delta 非 0 整数;核减穿零由服务端 400 诚实拒。
 */
export function validateCreditAdjust(deltaInput: string, reason: string): string | null {
  if (!reason.trim()) return '调整原因必填(审计口径)';
  const n = Number(deltaInput);
  if (deltaInput.trim() === '' || !Number.isFinite(n)) return '请输入有效的调整数值';
  if (!Number.isInteger(n)) return '调整数值必须是整数(1 次问询 = 1 积分)';
  if (n === 0) return '调整数值不能为 0(充值请输入正数,核减请输入负数)';
  return null;
}

/**
 * 台账 reason 机读枚举 → 人话。admin_adjust 在服务端落「admin_adjust: 详情」
 * 复合形态,拆前缀呈现;未知值原样透传(诚实律:不编造、不吞)。
 */
export function describeCreditReason(reason: string | null | undefined): string {
  if (!reason) return '—';
  if (reason === 'initial_grant') return '初始赠送';
  if (reason === 'consume') return '问询消耗';
  if (reason === 'refund') return '失败退回';
  if (reason === 'admin_adjust') return '平台调整';
  if (reason.startsWith('admin_adjust: ')) return `平台调整:${reason.slice('admin_adjust: '.length)}`;
  return reason;
}

/** delta 呈现:正数显式带 +(充值方向),负数原生带 -,缺值诚实「—」。 */
export function formatCreditDelta(delta: number | null | undefined): string {
  if (delta === null || delta === undefined || !Number.isFinite(delta)) return '—';
  return delta > 0 ? `+${delta}` : String(delta);
}

/** 流水行时间呈现:缺值「—」,其余本地时区可读形。 */
export function formatCreditTime(iso: string | null | undefined): string {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '—';
  return d.toLocaleString('zh-CN', { hour12: false });
}
