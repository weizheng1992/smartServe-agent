// 坐席推卡构造层(客服优化批 2026-10-25):纯函数,无 React/socket 依赖 ——
// 卡片形状单点对齐 packages/types card.ts 判别联合,动作名落在 CARD_ACTIONS
// 闭集内(merchant 侧 CARD_ACTION_STRATEGIES 12 名全登记,顾客点击回流成聊天
// 消息 = C 级交互闭环;未登记动作渲染端返回 null 兜底,此处不造新动作名)。
//
// 诚实纪律:卡片只装坐席已知事实(context 聚合行/发货输入),严禁编造物流
// 节点(发货通知卡的轨迹 = 服务端诚实单节点同款文案,「轨迹待更新」)。
import { orderStatusMeta } from '@/lib/format';
import type { QuickRepliesData, RichCardBlock, TrackingTimelineData } from 'types';

/** 右栏最近订单行的最小形状(LiveDeskContext.recentOrders 元素)。 */
export interface DeskOrderBrief {
  orderId: string;
  status: string;
  totalAmount: number;
  createdAt: string | null;
}

/** 订单卡:顾客侧自带「查看物流轨迹/申请退款」按钮(回流成消息,坐席时间线
 *  可见;资金动作仍走 AI 技能 HITL,卡片按钮本身零直写)。status 走正典中文
 *  词面(orderStatusMeta 单点)—— 卡片是顾客可见面,原始英文码不出库外显。 */
export function buildOrderCard(o: DeskOrderBrief): RichCardBlock {
  return {
    type: 'order_card',
    data: {
      orderId: o.orderId,
      status: orderStatusMeta(o.status).label,
      totalAmount: o.totalAmount,
      createdAt: o.createdAt || undefined,
      actions: [
        { label: '查看物流轨迹', action: 'track_order', payload: { orderId: o.orderId } },
        { label: '申请退款', action: 'request_refund', payload: { orderId: o.orderId } },
      ],
    },
  };
}

/** 发货通知卡(发货成功后自动推):与网关 ship_order 落库的诚实单节点轨迹
 *  同款事实 —— 承运商 + 运单号 + 轨迹待更新,不宣称在途/派送。 */
export function buildShippedTrackingCard(carrierLabel: string, trackingNo: string): RichCardBlock {
  const data: TrackingTimelineData = {
    trackingNumber: trackingNo,
    carrier: carrierLabel,
    currentStatus: '已发货',
    timeline: [
      {
        time: new Date().toISOString(),
        description: `商家已发货 · ${carrierLabel} · 运单号 ${trackingNo}，物流轨迹待更新`,
        status: 'completed',
      },
    ],
  };
  return { type: 'tracking_timeline', data };
}

/** 承运商词表单点在 lib/format(本 app 两处消费:发货弹窗/坐席台);此处
 *  转出口保持既有导入面稳定。跨语言互指:gateway _CARRIER_LABELS、商城
 *  logistics.ts。 */
export { CARRIER_OPTIONS, carrierLabelOf } from '@/lib/format';

/** 快捷回复卡预设:坐席一键推选项卡,顾客点选即回流一条消息(send_message
 *  动作 payload.text = 选项文案)。预设是 v1 词面,后续可做配置化。 */
export interface QuickReplyPreset {
  id: string;
  title: string;
  options: string[];
}

export const QUICK_REPLY_PRESETS: QuickReplyPreset[] = [
  {
    id: 'consult-type',
    title: '请选择您要咨询的问题类型',
    options: ['查询物流', '申请退换货', '商品咨询', '优惠活动', '其他问题'],
  },
  {
    id: 'aftersale-choice',
    title: '您的售后申请希望如何处理?',
    options: ['继续办理退款', '申请换货', '再考虑一下'],
  },
];

export function buildQuickRepliesCard(preset: QuickReplyPreset): RichCardBlock {
  const data: QuickRepliesData = {
    title: preset.title,
    options: preset.options.map((label) => ({
      label,
      action: 'send_message',
      payload: { text: label },
    })),
  };
  return { type: 'quick_replies', data };
}
