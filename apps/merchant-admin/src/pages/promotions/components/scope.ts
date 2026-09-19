// 活动适用范围展示与取值(纯逻辑,便于单测)。
//
// 引擎语义(promotion_engine.py):仅 `spu` 范围真实生效(scope_value=单个
// spu_code 明文);`category` 未实现(等于全局生效且优先级更高,UI 不提供);
// 券型(coupon)完全无视范围 —— 表单对券型不展示范围字段。

export type ScopeType = 'all' | 'spu';

/** 范围展示文案;spuTitles 供「指定商品」回显商品标题(查不到回退编码)。 */
export function scopeLabel(scopeType: string | null, scopeValue: string | null, spuTitles: Record<string, string> = {}): string {
  if (!scopeType || scopeType === 'all') return '全部商品';
  if (scopeType === 'spu') {
    const title = scopeValue ? spuTitles[scopeValue] : undefined;
    return title ? `指定商品:${title}` : `指定商品:${scopeValue || '未设置'}`;
  }
  return `范围:${scopeType}`;
}

/** 券型不展示范围选择(引擎对券无视范围,展示即误导)。 */
export function scopeEditableFor(promoType: string): boolean {
  return promoType !== 'coupon';
}
