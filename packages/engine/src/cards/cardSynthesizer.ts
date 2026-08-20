import type {
  DamageAssessmentData,
  OrderCardData,
  QuickRepliesData,
  RefundConfirmationData,
  RichCardBlock,
  TrackingTimelineData,
} from "types";

export class CardSynthesizer {
  /**
   * 自动根据执行任务结果与意图合成富媒体卡片
   */
  static synthesizeCards(options: {
    taskPlan?: any;
    intents?: any[];
    damageAssessment?: DamageAssessmentData;
    quickReplies?: string[];
  }): RichCardBlock[] {
    const cards: RichCardBlock[] = [];
    const { taskPlan, damageAssessment } = options;

    // 1. 如果有商品破损定责评估结果，追加破损定责卡
    if (damageAssessment) {
      cards.push({
        type: "damage_assessment",
        data: damageAssessment,
      });
    }

    if (taskPlan?.subtasks) {
      for (const st of taskPlan.subtasks) {
        const result = st.result?.output || st.result;
        if (!result) continue;

        // 2. 识别并提取订单详情卡与物流轨迹卡
        if (
          result.orderId &&
          (result.status || result.carrier || result.trackingNumber)
        ) {
          const orderCard: OrderCardData = {
            orderId: result.orderId,
            status: result.status || "Shipped",
            totalAmount: result.totalAmount || result.amount || 129.0,
            currency: result.currency || "USD",
            carrier: result.carrier || "SF Express",
            trackingNumber: result.trackingNumber || "SF10928374",
            createdAt: result.createdAt || new Date().toISOString(),
            actions: [
              {
                label: "查看物流轨迹",
                action: "track_order",
                payload: { orderId: result.orderId },
              },
              {
                label: "申请退款",
                action: "request_refund",
                payload: { orderId: result.orderId },
              },
            ],
          };
          cards.push({ type: "order_card", data: orderCard });

          if (result.trackingNumber || result.carrier) {
            const timelineCard: TrackingTimelineData = {
              trackingNumber: result.trackingNumber || "SF10928374",
              carrier: result.carrier || "SF Express",
              currentStatus: result.status || "In Transit",
              estimatedDelivery: result.estimatedDelivery || "2026-08-22 18:00",
              timeline: [
                {
                  time: "2026-08-20 09:30",
                  location: "上海转运中心",
                  description: "包裹已到达上海分拨枢纽，准备发往下一站",
                  status: "in_transit",
                },
                {
                  time: "2026-08-19 14:15",
                  location: "杭州保税仓",
                  description: "包裹已出库，由顺丰速运揽收",
                  status: "completed",
                },
                {
                  time: "2026-08-19 10:00",
                  location: "系统下单",
                  description: "订单支付成功，仓库正在打包商品",
                  status: "completed",
                },
              ],
            };
            cards.push({ type: "tracking_timeline", data: timelineCard });
          }
        }

        // 3. 识别退款执行与核签卡
        if (
          st.id?.includes("refund") ||
          st.description?.includes("refund") ||
          result.refundAmount ||
          result.refundId
        ) {
          const refundCard: RefundConfirmationData = {
            orderId: result.orderId || "ORD-98712",
            refundAmount: result.refundAmount || result.amount || 129.0,
            currency: result.currency || "USD",
            refundReason: result.reason || "商品破损/七天无理由退款",
            refundMethod: "原路返回支付账户 (Original Payment Method)",
            status: result.waitingForApproval
              ? "pending_confirmation"
              : result.success
                ? "approved"
                : "submitted",
            requiresApproval: !!result.waitingForApproval,
          };
          cards.push({ type: "refund_confirmation", data: refundCard });
        }
      }
    }

    // 4. 默认快捷回复胶囊 (Quick Replies)
    const quickRepliesOptions: QuickRepliesData = {
      title: "您可能需要：",
      options: [
        {
          label: "📦 查询物流进度",
          action: "send_message",
          payload: { text: "帮我查一下最新物流发货进度" },
        },
        {
          label: "💰 申请退款服务",
          action: "send_message",
          payload: { text: "我想申请退款" },
        },
        {
          label: "📷 上传商品瑕疵照片",
          action: "trigger_upload",
          payload: { prompt: "上传商品照片核验" },
        },
        {
          label: "🎧 呼叫人工客服",
          action: "send_message",
          payload: { text: "转人工" },
        },
      ],
    };
    cards.push({ type: "quick_replies", data: quickRepliesOptions });

    return cards;
  }
}
