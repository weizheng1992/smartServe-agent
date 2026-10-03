// 多租户品牌隔离 scorer(端到端真跑用例):
// 断言回复以本租户品牌自称(forbiddenBrand 他牌零串入 —— 种子用户在三租户
// 名下都有订单,订单工具若不按 business_id 过滤,此处会直接红),且无
// [ECOMMERCE] 品牌前缀幻觉残留(0adf7b6 回归锚)。
export default function (output: string, context: any) {
  const brand = String(context.vars.expectedBrand || '');
  const forbidden = String(context.vars.forbiddenBrand || '');
  if (!brand) {
    return { pass: false, score: 0, reason: 'vars.expectedBrand 未设置,scorer 无法判定' };
  }
  if (!output.includes(brand)) {
    return {
      pass: false,
      score: 0,
      reason: `回复未体现本租户品牌「${brand}」:${output.slice(0, 120)}`,
    };
  }
  if (forbidden && output.includes(forbidden)) {
    return {
      pass: false,
      score: 0,
      reason: `回复串入他牌「${forbidden}」,租户隔离破防:${output.slice(0, 120)}`,
    };
  }
  if (output.includes('[ECOMMERCE]')) {
    return { pass: false, score: 0, reason: '回复残留 [ECOMMERCE] 品牌前缀幻觉' };
  }
  return { pass: true, score: 1, reason: `品牌自识别与隔离通过(${brand})` };
}
