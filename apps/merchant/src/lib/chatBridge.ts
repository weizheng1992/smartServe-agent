// 前台页面 → 悬浮客服窗的打开桥(2026-09-29 评审 ② 收口:订单面三处
// onOpenChatWithOrder 此前都是 () => {} 空函数,弹窗里的「咨询客服」点了
// 没有任何反应)。事件广播型接线,与 storeCart 的 cart_updated 同型:
// 悬浮窗单实例挂在 App 根部,页面组件与其无父子关系,props 够不着。
// 收到事件即开窗;detail.message 存在则预填输入框(不自动发送,由顾客
// 确认后发出 —— 咨询意图免打字,但不替顾客按发送键)。

export const STOREFRONT_CHAT_OPEN_EVENT = 'aurora_store_chat_open';

export interface StorefrontChatOpenDetail {
  message?: string;
}

export function openStorefrontChat(detail: StorefrontChatOpenDetail = {}): void {
  window.dispatchEvent(new CustomEvent(STOREFRONT_CHAT_OPEN_EVENT, { detail }));
}
