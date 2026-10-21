// 配额拒引导映射(2026-10-21 配额闸票 06,.scratch/agent-usage-quota spec §5)。
// 后端契约:POST /api/chat 配额拒时信封带 quotaCode(QUOTA_* 机读码,增量键),
// SSE result 帧 data 同携 quotaCode 且 output 为后端权威中文文案。
//
// 数据诚实律:本模块只做「机读码 → 固定操作建议」的闭集映射 + 文案拼装,
// 后端 output 照实展示在前;严禁编造剩余额度数字、重置时刻等任何后端未给
// 的事实。未知码不猜,只透传 output。

/** 后端配额机读码闭集(gateway_py/quota.py 契约) */
export const QUOTA_CODES = [
  'QUOTA_GUEST_LIMIT',
  'QUOTA_IP_LIMIT',
  'QUOTA_USER_DAILY',
  'QUOTA_MERCHANT_EXHAUSTED',
] as const;

export type QuotaCode = (typeof QUOTA_CODES)[number];

/** 闭集判定:SSE/信封增量键是线上数据,未知码不进映射(诚实兜底) */
export function isQuotaCode(value: unknown): value is QuotaCode {
  return typeof value === 'string' && (QUOTA_CODES as readonly string[]).includes(value);
}

/**
 * 机读码 → 操作建议(纯引导短语,不含任何额度数字)。
 * 未知码返回空串 —— 调用方只展示后端 output,不编造建议。
 */
export function quotaAdviceOf(code: string): string {
  switch (code) {
    case 'QUOTA_USER_DAILY':
      return '明天再试';
    case 'QUOTA_MERCHANT_EXHAUSTED':
      return '联系商户';
    case 'QUOTA_GUEST_LIMIT':
    case 'QUOTA_IP_LIMIT':
      // web 面强制 JWT,游客码理论上不可达;仍按票面兜底给注册/登录提示
      return '注册或登录后再试';
    default:
      return '';
  }
}

/**
 * 配额拒气泡正文:后端 output 照实在前,固定操作建议在后。
 * output 缺失(理论不可达,防御臂)时诚实说明被拒,不空白、不编造详情。
 */
export function quotaBubbleText(code: string, output: string): string {
  const base = (output || '').trim();
  const advice = quotaAdviceOf(code);
  if (!base) {
    return advice ? `本次问询未能受理。建议您：${advice}。` : '本次问询未能受理。';
  }
  return advice ? `${base}\n\n建议您：${advice}。` : base;
}
