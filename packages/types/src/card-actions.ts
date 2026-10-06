/**
 * 卡片动作目录(F3,2026-10-06):引擎富卡片 `action` 字段的闭集单一事实源。
 *
 * 此前 web(cardActions.ts)与 merchant(FloatingChatWidget CARD_ACTION_STRATEGIES)
 * 各持一份动作分发表,引擎新增动作时两表独立漂移(修复 44c8159 前的死按钮即
 * 此病)。动作的**处置语义**按 app 刻意不同(web 无商城车页:结算类动作转聊天
 * 消息;merchant:结算类动作 redirect 商城车页)—— 收口的只是动作名闭集与
 * payload 形状:两表以 `Record<CardActionName, ...>` 类型化后,缺键/多键/
 * 引擎新动作未登记均在编译期与目录契约测试双红灯。
 */

export const CARD_ACTIONS = [
  'send_message',
  'select_order',
  'track_order',
  'request_refund',
  'confirm_refund',
  'submit_return_tracking',
  'submit_step_action',
  'add_to_cart_interactive',
  'buy_now_interactive',
  'checkout_cart',
  'view_cart',
  'clear_cart',
] as const;

export type CardActionName = (typeof CARD_ACTIONS)[number];

/** 动作 payload 形状(引擎卡片 actions[].payload;字段按动作可选)。 */
export interface CardActionPayload {
  text?: string;
  orderId?: string;
  value?: string;
  title?: string;
  skuTitle?: string;
  skuId?: string;
  quantity?: number;
  order?: Record<string, unknown>;
  query?: string;
  [key: string]: unknown;
}
