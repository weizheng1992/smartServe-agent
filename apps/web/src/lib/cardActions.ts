// 卡片动作 → 用户消息文案:声明式分发表(2026-10-02 夜审修复A 收敛)。
// 此前 ChatArea 内联 if 链(仅 6 动作,其余 no-op 死按钮)与 ChatWidget 本地
// CARD_ACTION_HANDLERS(9 动作)各自漂移:引擎购物车卡实发的 checkout_cart /
// view_cart(skills/cart/cards.py CHECKOUT/VIEW_ACTIONS)与 clear_cart 在
// web 两处均无处理。两消费方收敛到本表;组件特有副作用(trigger_upload
// 开文件选择器)留组件局部。购物车三动作映射为聊天消息而非路由跳转:
// web 无商城 /cart 页(merchant 端 redirect:/cart 策略在此不适用),
// 三个词面恰是引擎购物车技能的真实触发词(intent_registry.CHECKOUT_FAMILY
// 的「去结算」/ resolver 查看分支「查看购物车」/ _CLEAR_RE「清空」);
// 裸「结算」是查看摘要旧契约,严禁作 checkout_cart 文案。

// payload 形状单一事实源在 types 目录(F3 收口补全,2026-10-07 夜评):本地
// Record<string, any> 宽类型曾使 payload 字段拼写在 web 侧零检查
import { type CardActionName, type CardActionPayload } from 'types';

export type { CardActionPayload };

export type CardActionHandler = (p: CardActionPayload) => string | null;

/** F3(2026-10-06):键集类型化 CardActionName —— 与 merchant 表同源 types 目录,
 *  缺键(引擎新动作未登记)/多键(死词)在编译期双红灯。 */
export const CARD_ACTION_HANDLERS: Record<CardActionName, CardActionHandler> = {
  send_message: (p) => (p.text ? String(p.text) : null),
  select_order: (p) => (p.orderId ? `查询订单 ${p.orderId} 的详细信息与可选业务` : null),
  track_order: (p) => (p.orderId ? `帮我查一下订单 ${p.orderId} 的物流轨迹` : null),
  request_refund: (p) => (p.orderId ? `帮我申请订单 ${p.orderId} 的退款` : null),
  confirm_refund: (p) => (p.orderId ? `我已确认提交订单 ${p.orderId} 的退款核签` : null),
  submit_return_tracking: (p) => (p.value ? `我已寄出商品，寄件快递单号为 ${p.value}，请跟进质检验收` : null),
  submit_step_action: (p) => (p.value ? `我已提交业务步骤信息：${p.value}` : null),
  add_to_cart_interactive: (p) => `我想将 ${p.title}（规格: ${p.skuTitle || p.skuId}）购买 ${p.quantity} 件加入购物车`,
  buy_now_interactive: (p) => `我想立即购买 ${p.title}（规格: ${p.skuTitle || p.skuId}）共 ${p.quantity} 件`,
  checkout_cart: () => '去结算',
  view_cart: () => '查看购物车',
  clear_cart: () => '清空购物车',
};

/** 查表解析卡片动作;未登记动作回落 payload.query(卡片自带原始问句)。 */
export function resolveCardActionMessage(action: string, payload: CardActionPayload): string | null {
  // F3:表键集经 CardActionName 编译期穷举;运行时未登记动作查不到 handler,
  // 回落 payload.query(卡片自带原始问句)—— 修复A 语义保留
  const handler = (CARD_ACTION_HANDLERS as Record<string, CardActionHandler>)[action];
  return handler ? handler(payload) : typeof payload.query === 'string' ? payload.query : null;
}
