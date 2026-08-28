import {
  AgentIntentType,
  type AgentTaskSpec,
  type OrderContext,
  type OrderTaskSlots,
} from "types";

/**
 * 必填槽位映射表
 */
export const REQUIRED_SLOTS_MAP: Record<string, string[]> = {
  [AgentIntentType.ORDER_MODIFY_ADDRESS]: ["orderId", "newAddress"],
  [AgentIntentType.ORDER_RETURN]: ["orderId"],
  [AgentIntentType.ORDER_CANCEL]: ["orderId"],
  [AgentIntentType.ORDER_QUERY]: ["orderId"],
};

export interface SlotExtractionContext {
  orderContext?: OrderContext;
  shortMemory?: any[];
  historyMsgs?: any[];
}

/**
 * 🎯 实体抽取与槽位对齐引擎 (Entity & Slot Alignment Engine)
 *
 * 职责划分：
 * 1. 专注单号、快递单、地址、退款原因、购买数量等关键实体的确定性抽取（微秒级）
 * 2. 多轮对话上下文继承与槽位对齐
 * 3. 槽位完整性校验与即时反问生成 (Clarification)
 * 4. 意图判别前置轻量规则，复杂意图与多意图交给 Embedding 向量层与结构化 LLM 层
 */
export class SlotExtractor {
  public static readonly ORDER_ID_REGEX =
    /(?:[A-Za-z0-9]+[-_])*ORD(?:[-_][A-Za-z0-9]+)+|\b[A-Za-z]{2,8}[-_]?\d{4,}\b|\b\d{8,}\b/i;

  public static readonly ADDRESS_KEYWORDS_REGEX =
    /(?:改成|改到|送至|送往|送去|寄到|寄往|改派到|改派|改送|新地址[是为:：]?|地址[是为:：])\s*([^,，!！?？\n]+)/i;

  public static readonly PROVINCE_CITY_REGEX =
    /(?:北京市|上海市|天津市|重庆市|广东省|浙江省|江苏省|四川省|湖北省|山东省|河南省|河北省|陕西省|福建省|湖南省|安徽省|辽宁省|江西省|广西|海南省|贵州省|云南省|山西省|吉林省|黑龙江省|内蒙古|新疆|西藏|青海|宁夏|海淀区|朝阳区|西城区|东城区|浦东新区|黄浦区|徐汇区|静安区)[^\s,，。!！?？\n]+/i;

  /**
   * 纯实体识别提取器 (Pure Entity Extractor)
   */
  public static extractEntities(
    input: string,
    context?: SlotExtractionContext,
  ): Partial<OrderTaskSlots> {
    const text = input.trim();
    const entities: Partial<OrderTaskSlots> = {};

    // 1. 提取 orderId
    const orderMatch = text.match(this.ORDER_ID_REGEX);
    if (orderMatch && orderMatch[0]) {
      entities.orderId = orderMatch[0].toUpperCase();
    } else if (context?.orderContext?.targetOrderId) {
      entities.orderId = context.orderContext.targetOrderId.toUpperCase();
    } else {
      const msgs = context?.shortMemory || context?.historyMsgs || [];
      if (Array.isArray(msgs) && msgs.length > 0) {
        for (let i = msgs.length - 1; i >= 0; i--) {
          const msg = msgs[i];
          const content = typeof msg === "string" ? msg : msg?.content;
          if (content && typeof content === "string") {
            const histOrderMatch = content.match(this.ORDER_ID_REGEX);
            if (histOrderMatch && histOrderMatch[0]) {
              entities.orderId = histOrderMatch[0].toUpperCase();
              break;
            }
          }
        }
      }
    }

    // 2. 提取 newAddress
    const addrKwMatch = text.match(this.ADDRESS_KEYWORDS_REGEX);
    if (addrKwMatch && addrKwMatch[1]) {
      entities.newAddress = addrKwMatch[1].trim();
    } else {
      const provMatch = text.match(this.PROVINCE_CITY_REGEX);
      if (provMatch && provMatch[0]) {
        entities.newAddress = provMatch[0].trim();
      }
    }

    // 3. 提取 returnReason
    if (
      text.includes("尺码") ||
      text.includes("穿不上") ||
      text.includes("大") ||
      text.includes("小")
    ) {
      entities.returnReason = "wrong_size";
    } else if (
      text.includes("质量") ||
      text.includes("坏") ||
      text.includes("破") ||
      text.includes("瑕疵")
    ) {
      entities.returnReason = "quality_issue";
    } else if (
      text.includes("不符合") ||
      text.includes("不一样") ||
      text.includes("虚假")
    ) {
      entities.returnReason = "not_as_described";
    } else if (
      text.includes("七天") ||
      text.includes("不喜欢") ||
      text.includes("不想要")
    ) {
      entities.returnReason = "no_reason_7d";
    }

    return entities;
  }

  /**
   * 结构化槽位与意图抽取器 (兼容单轮/多轮槽位对齐)
   */
  public static extract(
    input: string,
    activeIntentContext?: string,
    existingSlots?: OrderTaskSlots,
    context?: SlotExtractionContext,
  ): AgentTaskSpec {
    const text = input.trim();

    // 1. 轻量规则识别显式意图（若有 activeIntentContext 则以其为准）
    let intentType: AgentIntentType = AgentIntentType.CHAT;
    let confidence = 0.9;

    const isCancelOrder = /(?:取消订单|撤销订单|退订|取消.*单)/i.test(text);
    const isCartManage =
      /(?:加购物车|加入购物车|放进购物车|加购|购物车|结算|去结算|去买单|查看购物车|清空购物车|购物车里|移出购物车|删除.*?购物车|从购物车.*?删除|买第|件加入|款加入|放入购物车|加第|买第|要第|改成\s*\d+|修改为\s*\d+|数量设为\s*\d+|第[一二三四五12345两几][件款个双].*?(?:购物车|买|要|加|删|改|去)|(?:删除|移除|删掉).*?第[一二三四五12345两几][件款个双])/i.test(
        text,
      ) || /^(?:把)?第\s*[一二三四五12345两几]\s*[件款个双]/.test(text);

    const isShoppingGuide =
      /(?:推荐|买什么|有什么好看|有没有|挑一款|选一款|适合.*的|找一找|推荐一款|介绍一下|哪款好|选鞋|选衣服|看商品|导购|什么牌子|款式|推荐几件)/i.test(
        text,
      ) && !isCartManage;

    const isOrderQuery =
      /(?:查.*物流|物流到哪|物流信息|快递单号|快递到哪|发货了吗|包裹到哪|查快递|寄到哪|送至哪|到了没|查一下.*订单|查订单状态|查询.*订单|物流查询|查下订单|查订单|我的订单|名下.*订单|全部订单)/i.test(
        text,
      ) &&
      !/(?:寄到|送至|送往|寄往|送去)\s*(?:哪里|哪儿|哪了|何处|\?|？)/i.test(
        text,
      );

    const isModifyAddress =
      (/(?:修改|更改|变更|换|改|更新).*?(?:收货)?(?:地址|位置|地方)/i.test(
        text,
      ) ||
        /(?:收货)?(?:地址|位置|地方).*?(?:修改|更改|变更|换|改|错|变)/i.test(
          text,
        ) ||
        /(?:改到|改成|送至|送往|改派到|改派|改送)\s*[^?？哪里哪儿\n]+/i.test(
          text,
        )) &&
      !/(?:寄到|送至|送往|寄往|送去)\s*(?:哪里|哪儿|哪了|何处|\?|？)/i.test(
        text,
      );

    const isReturnOrRefund = /(?:退货|退款|退单|申请售后|退钱|不想要了)/i.test(
      text,
    );
    const isMetricQuery =
      /(?:销售额|销量|出货量|毛利|利润率|gmv|滞销|排行|最卖钱|最赚钱)/i.test(
        text,
      );

    if (activeIntentContext) {
      intentType = activeIntentContext as AgentIntentType;
      confidence = 0.95;
    } else if (isCartManage) {
      intentType = AgentIntentType.CART_MANAGE;
      confidence = 0.95;
    } else if (isShoppingGuide) {
      intentType = AgentIntentType.SHOPPING_GUIDE;
      confidence = 0.95;
    } else if (isModifyAddress) {
      intentType = AgentIntentType.ORDER_MODIFY_ADDRESS;
      confidence = 0.95;
    } else if (isCancelOrder) {
      intentType = AgentIntentType.ORDER_CANCEL;
      confidence = 0.92;
    } else if (isReturnOrRefund) {
      intentType = AgentIntentType.ORDER_RETURN;
      confidence = 0.95;
    } else if (isOrderQuery) {
      intentType = AgentIntentType.ORDER_QUERY;
      confidence = 0.92;
    } else if (isMetricQuery) {
      intentType = AgentIntentType.METRIC_QUERY;
      confidence = 0.96;
    }

    // 2. 槽位提取与多轮对齐
    const extractedEntities = this.extractEntities(text, context);
    const slots: OrderTaskSlots = {
      ...(existingSlots || {}),
      ...extractedEntities,
    };

    // 3. 计算缺失槽位 (Missing Slots)
    const required = REQUIRED_SLOTS_MAP[intentType] || [];
    const missingSlots: string[] = [];

    const isGeneralOrderList =
      intentType === AgentIntentType.ORDER_QUERY &&
      /(?:我的订单|全部订单|名下.*订单|所有订单|历史订单|查订单|查询.*订单|查下订单|订单列表)/i.test(
        text,
      ) &&
      !/(?:查.*物流|物流到哪|物流信息|快递单号|快递到哪|发货了吗|包裹到哪|查快递)/i.test(
        text,
      );

    for (const reqSlot of required) {
      if (reqSlot === "orderId" && isGeneralOrderList) {
        continue;
      }
      if (!slots[reqSlot as keyof OrderTaskSlots]) {
        missingSlots.push(reqSlot);
      }
    }

    // 4. 生成多轮即时反问话术 (Clarification Message)
    let clarificationMessage: string | undefined;

    if (missingSlots.length > 0) {
      if (intentType === AgentIntentType.ORDER_MODIFY_ADDRESS) {
        if (
          missingSlots.includes("orderId") &&
          missingSlots.includes("newAddress")
        ) {
          clarificationMessage =
            "好的，请问您需要修改哪笔订单的收货地址？请提供您的【订单编号】（如 ORD-889901）以及【新的收货地址】。";
        } else if (missingSlots.includes("newAddress")) {
          clarificationMessage = `已为您定位到订单 [${slots.orderId}]，请问您需要将收货地址变更为哪个新的收货地址？`;
        } else if (missingSlots.includes("orderId")) {
          clarificationMessage = `收到您的新地址 [${slots.newAddress}]，请问您需要修改哪笔【订单编号】的收货地址？`;
        }
      } else if (intentType === AgentIntentType.ORDER_RETURN) {
        if (missingSlots.includes("orderId")) {
          clarificationMessage =
            "请问您需要为哪笔订单申请退款/退货？请提供您的【订单编号】。";
        }
      } else if (intentType === AgentIntentType.ORDER_CANCEL) {
        if (missingSlots.includes("orderId")) {
          clarificationMessage = "请问您需要取消哪笔订单？请提供【订单编号】。";
        }
      } else if (intentType === AgentIntentType.ORDER_QUERY) {
        if (missingSlots.includes("orderId")) {
          clarificationMessage = "请提供您需要查询的【订单编号】或【运单号】。";
        }
      }
    }

    return {
      intentType,
      slots,
      confidence,
      missingSlots,
      clarificationMessage,
    };
  }

  /**
   * 复合多意图抽取器
   */
  public static extractAll(
    input: string,
    activeIntentContext?: string,
    existingSlots?: OrderTaskSlots,
    context?: SlotExtractionContext,
  ): AgentTaskSpec[] {
    const text = input.trim();

    const isCancelOrder = /(?:取消订单|撤销订单|退订|取消.*单)/i.test(text);
    const isCartManage =
      /(?:加购物车|加入购物车|放进购物车|加购|购物车|结算|去结算|去买单|查看购物车|清空购物车|购物车里|移出购物车|删除.*?购物车|从购物车.*?删除|买第|件加入|款加入|放入购物车|加第|买第|要第|改成\s*\d+|修改为\s*\d+|数量设为\s*\d+|第[一二三四五12345两几][件款个双].*?(?:购物车|买|要|加|删|改|去)|(?:删除|移除|删掉).*?第[一二三四五12345两几][件款个双])/i.test(
        text,
      ) || /^(?:把)?第\s*[一二三四五12345两几]\s*[件款个双]/.test(text);

    const isShoppingGuide =
      /(?:推荐|买什么|有什么好看|有没有|挑一款|选一款|适合.*的|找一找|推荐一款|介绍一下|哪款好|选鞋|选衣服|看商品|导购|什么牌子|款式|推荐几件|推荐几款)/i.test(
        text,
      ) && !isCartManage;

    const isOrderQuery =
      /(?:查.*物流|物流到哪|物流信息|快递单号|快递到哪|发货了吗|包裹到哪|查快递|寄到哪|送至哪|到了没|查一下.*订单|查订单状态|查询.*订单|物流查询|查下订单|查订单|我的订单|名下.*订单|全部订单)/i.test(
        text,
      ) &&
      !/(?:寄到|送至|送往|寄往|送去)\s*(?:哪里|哪儿|哪了|何处|\?|？)/i.test(
        text,
      );

    const isModifyAddress =
      (/(?:修改|更改|变更|换|改|更新).*?(?:收货)?(?:地址|位置|地方)/i.test(
        text,
      ) ||
        /(?:收货)?(?:地址|位置|地方).*?(?:修改|更改|变更|换|改|错|变)/i.test(
          text,
        ) ||
        /(?:改到|改成|送至|送往|改派到|改派|改送)\s*[^?？哪里哪儿\n]+/i.test(
          text,
        )) &&
      !/(?:寄到|送至|送往|寄往|送去)\s*(?:哪里|哪儿|哪了|何处|\?|？)/i.test(
        text,
      );

    const isReturnOrRefund =
      /(?:退货|退款|退单|申请售后|退钱|不想要了|申请退款)/i.test(text);
    const isMetricQuery =
      /(?:销售额|销量|出货量|毛利|利润率|gmv|滞销|排行|最卖钱|最赚钱)/i.test(
        text,
      );

    const detectedIntents: AgentIntentType[] = [];
    if (isShoppingGuide) detectedIntents.push(AgentIntentType.SHOPPING_GUIDE);
    if (isCartManage) detectedIntents.push(AgentIntentType.CART_MANAGE);
    if (isOrderQuery) detectedIntents.push(AgentIntentType.ORDER_QUERY);
    if (isModifyAddress)
      detectedIntents.push(AgentIntentType.ORDER_MODIFY_ADDRESS);
    if (isReturnOrRefund) detectedIntents.push(AgentIntentType.ORDER_RETURN);
    if (isCancelOrder) detectedIntents.push(AgentIntentType.ORDER_CANCEL);
    if (isMetricQuery) detectedIntents.push(AgentIntentType.METRIC_QUERY);

    if (detectedIntents.length <= 1) {
      return [
        SlotExtractor.extract(
          input,
          activeIntentContext,
          existingSlots,
          context,
        ),
      ];
    }

    return detectedIntents.map((it) =>
      SlotExtractor.extract(input, it, existingSlots, context),
    );
  }
}
