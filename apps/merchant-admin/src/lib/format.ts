// 全站金额与订单状态呈现单点(2026-10-15 候选③「数据诚实律与领域词汇模块化」;
// LOW_STOCK_THRESHOLD 单源与 fmtMoney 首砖已于快修五连落地)。
// 此前:金额 6 处 4 种方言(orders-tab 裸奔/守律版/去.00/裸拼)、订单状态 4 文件
// 3 份映射(DELIVERED「已签收/已送达」两词漂移)—— 律是真的,execution 靠记。

/**
 * 金额诚实律单点:缺值/坏值「—」—— Number(null) === 0 必须先挡空值,否则缺
 * 金额渲染成假 ¥0.00。调用形:`¥{fmtMoney(row.total_amount)}`(缺值渲染「¥—」,
 * 与 ask-transcript 既有钉子一致)。
 *
 * @param trim true = 去整 .00(紧凑场景:坐席上下文栏「¥128」);默认完整两位。
 */
export function fmtMoney(v: unknown, trim = false): string {
  if (v === null || v === undefined || v === '') return '—';
  const n = Number(v);
  if (!Number.isFinite(n)) return '—';
  const fixed = n.toFixed(2);
  return trim ? fixed.replace(/\.00$/, '') : fixed;
}

/** 订单状态正典表(label + Badge tone)。DELIVERED 正典取订单管理域权威
 *  「已签收」(客户订单卡/分析卡随正典;此前「已送达」为漂移词)。 */
export const ORDER_STATUS_META: Record<string, { label: string; cls: string }> = {
  PAID: { label: '待发货', cls: 'bg-amber-100 text-amber-800 border-amber-200' },
  SHIPPED: { label: '已发货', cls: 'bg-blue-100 text-blue-800 border-blue-200' },
  DELIVERED: { label: '已签收', cls: 'bg-emerald-100 text-emerald-800 border-emerald-200' },
  REFUNDED: { label: '已退款', cls: 'bg-purple-100 text-purple-800 border-purple-200' },
  CANCELLED: { label: '已取消', cls: 'bg-rose-100 text-rose-800 border-rose-200' },
  COMPLETED: { label: '已完成', cls: 'bg-zinc-100 text-zinc-700 border-zinc-200' },
};

/** 未知状态的诚实兜底:原样展示枚举值,不编造文案。 */
export function orderStatusMeta(status: string): { label: string; cls: string } {
  return ORDER_STATUS_META[status] || { label: status, cls: 'bg-slate-100 text-slate-800 border-slate-200' };
}

/** 积分台账 reason 机读枚举呈现(2026-10-21 用量配额闸)。admin_adjust 在服务端
 *  落「admin_adjust: 详情」复合形态,拆前缀呈现;未知值原样透传(诚实律)。 */
export function creditReasonMeta(reason: string | null | undefined): string {
  if (!reason) return '—';
  if (reason === 'initial_grant') return '初始赠送';
  if (reason === 'consume') return '问询消耗';
  if (reason === 'refund') return '失败退回';
  if (reason === 'admin_adjust') return '平台调整';
  if (reason.startsWith('admin_adjust: ')) return `平台调整:${reason.slice('admin_adjust: '.length)}`;
  return reason;
}
