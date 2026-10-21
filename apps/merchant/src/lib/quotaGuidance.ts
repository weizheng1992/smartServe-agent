// 配额拒引导映射(2026-10-21 配额闸票 06,.scratch/agent-usage-quota spec §5)。
// 后端契约:POST /api/store/chat 配额拒时信封 success=false + quotaCode
// (QUOTA_* 机读码)+ output(后端权威中文文案),HTTP 200。
//
// 数据诚实律:后端 output 照实展示,严禁编造剩余额度数字;游客(guest-*)
// 命中游客/网络码时追加注册/登录引导(指认页头用户菜单真实入口,不承诺
// 「注册后即可继续」—— 商户池耗尽时注册也帮不上忙);其余身份/码型只照实
// 显示 output。未知码不猜,只透传 output。

/** 后端配额机读码闭集(gateway_py/quota.py 契约) */
export const QUOTA_CODES = [
  'QUOTA_GUEST_LIMIT',
  'QUOTA_IP_LIMIT',
  'QUOTA_USER_DAILY',
  'QUOTA_MERCHANT_EXHAUSTED',
] as const;

export type QuotaCode = (typeof QUOTA_CODES)[number];

/** 游客判定(guest-* 前缀,U2 浏览器级稳定 ID;与 CUST-* 真客隔断) */
export function isGuestUserId(userId: string): boolean {
  return typeof userId === 'string' && userId.startsWith('guest-');
}

/**
 * 配额拒气泡正文:
 * - 游客 + 游客额度/网络环境码 → 后端文案照实 + 注册/登录引导;
 * - 其余(登录身份日顶/商户池尽、游客撞池尽等)→ 照实显示 output,
 *   不附注册引导(注册改变不了该拒绝,附了即误导)。
 * output 缺失(理论不可达,防御臂)时诚实说明被拒,不空白、不编造详情。
 */
export function quotaReplyText(quotaCode: string, output: string, userId: string): string {
  const base = (output || '').trim() || '本次问询未能受理。';
  const guestGuidance =
    isGuestUserId(userId) && (quotaCode === 'QUOTA_GUEST_LIMIT' || quotaCode === 'QUOTA_IP_LIMIT');
  return guestGuidance
    ? `${base}\n\n如需以正式顾客身份使用，可点击页面右上角的用户菜单登录或注册。`
    : base;
}
