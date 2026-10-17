// 发货面可选的四家承运商编码 → 展示名(商户台发货表单全集,ship-dialog 同款),未知编码原样透出
// (自 OrderDetailModal 本地映射整表迁入,键集恰为四家,无增量合并)
export const CARRIER_LABELS: Record<string, string> = {
  SF: '顺丰速运',
  JD: '京东快递',
  ZTO: '中通快递',
  EMS: '邮政 EMS',
};

/**
 * 承运商编码译名:缺失返回空串(调用方自行决定「待确认」类诚实文案,严禁虚构缺省承运商),
 * 未知编码原样透传。
 */
export function carrierLabel(code?: string | null): string {
  if (!code) return '';
  return CARRIER_LABELS[code] || code;
}
