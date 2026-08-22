import type {
  DamageAssessmentData,
  IntentResult,
  OrderCardData,
  ProductRankingCardData,
  QuickRepliesData,
  RankedProductItem,
  RefundConfirmationData,
  RichCardBlock,
  TaskPlan,
  TrackingTimelineData,
} from "types";

export interface SynthesizeCardsOptions {
  taskPlan?: TaskPlan;
  intents?: IntentResult[];
  damageAssessment?: DamageAssessmentData;
  quickReplies?: string[];
}

export class CardSynthesizer {
  /**
   * 自动根据执行任务结果与意图合成富媒体卡片 (Type-Safe Rich Card Synthesizer)
   */
  static synthesizeCards(options: SynthesizeCardsOptions): RichCardBlock[] {
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
        const result = (st.result?.output || st.result) as
          Record<string, unknown> | undefined;
        if (!result || result.error) continue;

        const orderId =
          typeof result.orderId === "string" ? result.orderId : undefined;
        const status =
          typeof result.status === "string" ? result.status : undefined;
        const carrier =
          typeof result.carrier === "string" ? result.carrier : undefined;
        const trackingNumber =
          typeof result.trackingNumber === "string"
            ? result.trackingNumber
            : undefined;

        // 2. 识别并提取订单详情卡与物流轨迹卡 (来自于 getOrderStatus / listUserOrders)
        const ordersList: Array<Record<string, unknown>> = Array.isArray(
          result.orders,
        )
          ? (result.orders as Array<Record<string, unknown>>)
          : orderId && (status || carrier || trackingNumber)
            ? [result]
            : [];

        for (const ord of ordersList) {
          const ordId = (ord.orderId || ord.order_id) as string | undefined;
          const ordStatus = (ord.status as string) || "已确认";
          const ordCarrier = (ord.carrier as string) || "标准快递";
          const ordTrackingNumber =
            (ord.trackingNumber as string) ||
            (ord.tracking_number as string) ||
            "暂无运单号";
          if (!ordId) continue;

          const rawAmount = ord.totalAmount || ord.total_amount || ord.amount;
          const parsedAmount =
            typeof rawAmount === "number"
              ? rawAmount
              : typeof rawAmount === "string"
                ? Number.parseFloat(rawAmount.replace(/[^0-9.]/g, "")) || 0
                : 0;

          const orderCard: OrderCardData = {
            orderId: ordId,
            status: ordStatus,
            totalAmount: parsedAmount,
            currency: (ord.currency as string) || "USD",
            carrier: ordCarrier,
            trackingNumber: ordTrackingNumber,
            createdAt:
              (ord.createdAt as string) ||
              (ord.created_at as string) ||
              new Date().toISOString(),
            actions: [
              {
                label: "查看物流轨迹",
                action: "track_order",
                payload: { orderId: ordId },
              },
              {
                label: "申请退款",
                action: "request_refund",
                payload: { orderId: ordId },
              },
            ],
          };
          cards.push({ type: "order_card", data: orderCard });

          if (ordersList.length === 1 && (ordTrackingNumber || ordCarrier)) {
            const rawTimeline = Array.isArray(ord.timeline)
              ? (ord.timeline as TrackingTimelineData["timeline"])
              : [
                  {
                    time: new Date()
                      .toISOString()
                      .replace("T", " ")
                      .slice(0, 16),
                    location: `${ordCarrier} 派送中`,
                    description: `包裹正在运送中，状态：${ordStatus}`,
                    status: "in_transit" as const,
                  },
                  {
                    time: "订单发货",
                    location: "发货仓库",
                    description: "商品已完成质检并打包装箱出库",
                    status: "completed" as const,
                  },
                ];

            const timelineCard: TrackingTimelineData = {
              trackingNumber: ordTrackingNumber,
              carrier: ordCarrier,
              currentStatus: ordStatus,
              estimatedDelivery:
                (ord.estimatedDelivery as string) ||
                (ord.estimated_delivery as string) ||
                "预计 1-3 个工作日内送达",
              timeline: rawTimeline,
            };
            cards.push({ type: "tracking_timeline", data: timelineCard });
          }
        }

        // 3. 识别退款执行与核签卡 (来自于 processRefund)
        const isRefundTask =
          st.id?.includes("refund") ||
          st.description?.toLowerCase().includes("refund") ||
          result.refundAmount !== undefined ||
          result.refundId !== undefined;

        if (isRefundTask && orderId) {
          const rawRefundAmount = result.refundAmount || result.amount;
          const parsedRefundAmount =
            typeof rawRefundAmount === "number"
              ? rawRefundAmount
              : typeof rawRefundAmount === "string"
                ? Number.parseFloat(rawRefundAmount.replace(/[^0-9.]/g, "")) ||
                  0
                : 0;

          const refundCard: RefundConfirmationData = {
            orderId,
            refundAmount: parsedRefundAmount,
            currency: (result.currency as string) || "USD",
            refundReason: (result.reason as string) || "用户申请售后退款",
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

        // 4. 识别商品销售与多维排行卡 (来自于 queryProductRanking)
        const isProductRankingTask =
          st.id?.includes("ranking") ||
          st.description?.toLowerCase().includes("ranking") ||
          result.rankingMetric !== undefined ||
          (Array.isArray(result.products) && result.products.length > 0);

        if (isProductRankingTask && Array.isArray(result.products)) {
          const rankingCard: ProductRankingCardData = {
            rankingMetric: (result.rankingMetric as string) || "gmv",
            metricLabel: (result.metricLabel as string) || "总销售额 (GMV)",
            metricUnit: (result.metricUnit as string) || "元",
            itemCount: Number(result.itemCount || result.products.length),
            summary: (result.summary as string) || undefined,
            products: result.products as RankedProductItem[],
          };
          cards.push({ type: "product_ranking", data: rankingCard });
        }
      }
    }

    // 5. 智能快捷回复胶囊 (Quick Replies) - 优先挂载指标冲突组消歧切换按钮
    const hasRankingCard = cards.some((c) => c.type === "product_ranking");

    const quickRepliesOptions: QuickRepliesData = hasRankingCard
      ? {
          title: "您也可以一键切换其他统计口径：",
          options: [
            {
              label: "💰 按总销售额 (GMV)",
              action: "send_message",
              payload: { text: "按总销售额最高查询我负责的商品 Top 5" },
            },
            {
              label: "📦 按出货销量件数",
              action: "send_message",
              payload: { text: "按出货销量最高查询我负责的商品 Top 5" },
            },
            {
              label: "📈 按净毛利润金额",
              action: "send_message",
              payload: { text: "按净毛利润最高查询我负责的商品 Top 5" },
            },
            {
              label: "🎯 按单品毛利率 %",
              action: "send_message",
              payload: { text: "按毛利率最高查询我负责的商品 Top 5" },
            },
            {
              label: "⚠️ 排查滞销库存",
              action: "send_message",
              payload: { text: "排查我负责的滞销库存商品" },
            },
          ],
        }
      : {
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
