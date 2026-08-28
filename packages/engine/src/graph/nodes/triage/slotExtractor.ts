import {
  AgentIntentType,
  type AgentTaskSpec,
  type OrderContext,
  type OrderTaskSlots,
} from "types";

export interface SlotExtractionContext {
  orderContext?: OrderContext;
  shortMemory?: any[];
  historyMsgs?: any[];
}

/**
 * 🎯 1. 原子实体提取器 (Atomic Pure Entity Extractors)
 */
export class EntityExtractors {
  public static readonly ORDER_ID_REGEX =
    /(?:[A-Za-z0-9]+[-_])*ORD(?:[-_][A-Za-z0-9]+)+|\b[A-Za-z]{2,8}[-_]?\d{4,}\b|\b\d{8,}\b/i;

  public static readonly ADDRESS_KEYWORDS_REGEX =
    /(?:改成|改到|送至|送往|送去|寄到|寄往|改派到|改派|改送|新地址[是为:：]?|地址[是为:：])\s*([^,，!！?？\n]+)/i;

  public static readonly PROVINCE_CITY_REGEX =
    /(?:北京市|上海市|天津市|重庆市|广东省|浙江省|江苏省|四川省|湖北省|山东省|河南省|河北省|陕西省|福建省|湖南省|安徽省|辽宁省|江西省|广西|海南省|贵州省|云南省|山西省|吉林省|黑龙江省|内蒙古|新疆|西藏|青海|宁夏|海淀区|朝阳区|西城区|东城区|浦东新区|黄浦区|徐汇区|静安区)[^\s,，。!！?？\n]+/i;

  private static readonly RETURN_REASONS_MAP: Array<{
    reason: string;
    keywords: string[];
  }> = [
    { reason: "wrong_size", keywords: ["尺码", "穿不上", "大", "小"] },
    { reason: "quality_issue", keywords: ["质量", "坏", "破", "瑕疵"] },
    { reason: "not_as_described", keywords: ["不符合", "不一样", "虚假"] },
    { reason: "no_reason_7d", keywords: ["七天", "不喜欢", "不想要"] },
  ];

  public static extractOrderId(
    text: string,
    context?: SlotExtractionContext,
  ): string | undefined {
    const match = text.match(this.ORDER_ID_REGEX);
    if (match?.[0]) {
      return match[0].toUpperCase();
    }
    if (context?.orderContext?.targetOrderId) {
      return context.orderContext.targetOrderId.toUpperCase();
    }
    const msgs = context?.shortMemory || context?.historyMsgs || [];
    if (Array.isArray(msgs) && msgs.length > 0) {
      for (let i = msgs.length - 1; i >= 0; i--) {
        const msg = msgs[i];
        const content = typeof msg === "string" ? msg : msg?.content;
        if (content && typeof content === "string") {
          const histMatch = content.match(this.ORDER_ID_REGEX);
          if (histMatch?.[0]) {
            return histMatch[0].toUpperCase();
          }
        }
      }
    }
    return undefined;
  }

  public static extractNewAddress(text: string): string | undefined {
    const kwMatch = text.match(this.ADDRESS_KEYWORDS_REGEX);
    if (kwMatch?.[1]) {
      return kwMatch[1].trim();
    }
    const provMatch = text.match(this.PROVINCE_CITY_REGEX);
    if (provMatch?.[0]) {
      return provMatch[0].trim();
    }
    return undefined;
  }

  public static extractReturnReason(text: string): string | undefined {
    for (const item of this.RETURN_REASONS_MAP) {
      if (item.keywords.some((kw) => text.includes(kw))) {
        return item.reason;
      }
    }
    return undefined;
  }
}

/**
 * 🎯 2. 声明式意图匹配规则表 (Declarative Intent Detection Rules)
 */
export interface IntentRule {
  intent: AgentIntentType;
  confidence: number;
  pattern: RegExp;
  negativePattern?: RegExp;
}

export const INTENT_DETECTION_RULES: IntentRule[] = [
  {
    intent: AgentIntentType.CART_MANAGE,
    confidence: 0.95,
    pattern:
      /(?:加购物车|加入购物车|放进购物车|加购|购物车|结算|去结算|去买单|查看购物车|清空购物车|购物车里|移出购物车|删除.*?购物车|从购物车.*?删除|买第|件加入|款加入|放入购物车|加第|买第|要第|改成\s*\d+|修改为\s*\d+|数量设为\s*\d+|第[一二三四五12345两几][件款个双].*?(?:购物车|买|要|加|删|改|去)|(?:删除|移除|删掉).*?第[一二三四五12345两几][件款个双])|^(?:把)?第\s*[一二三四五12345两几]\s*[件款个双]/i,
  },
  {
    intent: AgentIntentType.SHOPPING_GUIDE,
    confidence: 0.95,
    pattern:
      /(?:推荐|买什么|有什么好看|有没有|挑一款|选一款|适合.*的|找一找|推荐一款|介绍一下|哪款好|选鞋|选衣服|看商品|导购|什么牌子|款式|推荐几件|推荐几款)/i,
    negativePattern:
      /(?:加购物车|加入购物车|放进购物车|加购|移出购物车|清空购物车)/i,
  },
  {
    intent: AgentIntentType.ORDER_MODIFY_ADDRESS,
    confidence: 0.95,
    pattern:
      /(?:(?:修改|更改|变更|换|改|更新).*?(?:收货)?(?:地址|位置|地方)|(?:收货)?(?:地址|位置|地方).*?(?:修改|更改|变更|换|改|错|变)|(?:改到|改成|送至|送往|改派到|改派|改送)\s*[^?？哪里哪儿\n]+)/i,
    negativePattern:
      /(?:寄到|送至|送往|寄往|送去)\s*(?:哪里|哪儿|哪了|何处|\?|？)/i,
  },
  {
    intent: AgentIntentType.ORDER_CANCEL,
    confidence: 0.92,
    pattern: /(?:取消订单|撤销订单|退订|取消.*单)/i,
  },
  {
    intent: AgentIntentType.ORDER_RETURN,
    confidence: 0.95,
    pattern: /(?:退货|退款|退单|申请售后|退钱|不想要了|申请退款)/i,
  },
  {
    intent: AgentIntentType.ORDER_QUERY,
    confidence: 0.92,
    pattern:
      /(?:查.*物流|物流到哪|物流信息|快递单号|快递到哪|发货了吗|包裹到哪|查快递|寄到哪|送至哪|到了没|查一下.*订单|查订单状态|查询.*订单|物流查询|查下订单|查订单|我的订单|名下.*订单|全部订单)/i,
    negativePattern:
      /(?:寄到|送至|送往|寄往|送去)\s*(?:哪里|哪儿|哪了|何处|\?|？)/i,
  },
  {
    intent: AgentIntentType.METRIC_QUERY,
    confidence: 0.96,
    pattern: /(?:销售额|销量|出货量|毛利|利润率|gmv|滞销|排行|最卖钱|最赚钱)/i,
  },
];

/**
 * 🎯 3. Schema 驱动的槽位声明 (Intent Slot Schema)
 */
export interface SlotDefinition {
  name: keyof OrderTaskSlots;
  isRequired: (text: string) => boolean;
  extractor: (
    text: string,
    context?: SlotExtractionContext,
  ) => string | undefined;
}

export interface IntentSchema {
  slots: SlotDefinition[];
  buildClarificationMessage?: (
    slots: OrderTaskSlots,
    missing: string[],
  ) => string | undefined;
}

const isGeneralOrderListQuery = (text: string) =>
  /(?:我的订单|全部订单|名下.*订单|所有订单|历史订单|查订单|查询.*订单|查下订单|订单列表|看看我买了啥|我有哪些订单|历史购买记录|查下我买的东西)/i.test(
    text,
  ) &&
  !/(?:查.*物流|物流到哪|物流信息|快递单号|快递到哪|发货了吗|包裹到哪|查快递)/i.test(
    text,
  );

export const INTENT_SCHEMAS: Partial<Record<AgentIntentType, IntentSchema>> = {
  [AgentIntentType.ORDER_MODIFY_ADDRESS]: {
    slots: [
      {
        name: "orderId",
        isRequired: () => true,
        extractor: (t, ctx) => EntityExtractors.extractOrderId(t, ctx),
      },
      {
        name: "newAddress",
        isRequired: () => true,
        extractor: (t) => EntityExtractors.extractNewAddress(t),
      },
    ],
    buildClarificationMessage: (slots, missing) => {
      if (missing.includes("orderId") && missing.includes("newAddress")) {
        return "好的，请问您需要修改哪笔订单的收货地址？请提供您的【订单编号】（如 ORD-889901）以及【新的收货地址】。";
      }
      if (missing.includes("newAddress")) {
        return `已为您定位到订单 [${slots.orderId}]，请问您需要将收货地址变更为哪个新的收货地址？`;
      }
      if (missing.includes("orderId")) {
        return `收到您的新地址 [${slots.newAddress}]，请问您需要修改哪笔【订单编号】的收货地址？`;
      }
      return undefined;
    },
  },
  [AgentIntentType.ORDER_RETURN]: {
    slots: [
      {
        name: "orderId",
        isRequired: () => true,
        extractor: (t, ctx) => EntityExtractors.extractOrderId(t, ctx),
      },
      {
        name: "returnReason",
        isRequired: () => false,
        extractor: (t) => EntityExtractors.extractReturnReason(t),
      },
    ],
    buildClarificationMessage: (_slots, missing) => {
      if (missing.includes("orderId")) {
        return "请问您需要为哪笔订单申请退款/退货？请提供您的【订单编号】。";
      }
      return undefined;
    },
  },
  [AgentIntentType.ORDER_CANCEL]: {
    slots: [
      {
        name: "orderId",
        isRequired: () => true,
        extractor: (t, ctx) => EntityExtractors.extractOrderId(t, ctx),
      },
    ],
    buildClarificationMessage: (_slots, missing) => {
      if (missing.includes("orderId")) {
        return "请问您需要取消哪笔订单？请提供【订单编号】。";
      }
      return undefined;
    },
  },
  [AgentIntentType.ORDER_QUERY]: {
    slots: [
      {
        name: "orderId",
        isRequired: (text) => !isGeneralOrderListQuery(text),
        extractor: (t, ctx) => EntityExtractors.extractOrderId(t, ctx),
      },
    ],
    buildClarificationMessage: (_slots, missing) => {
      if (missing.includes("orderId")) {
        return "请提供您需要查询的【订单编号】或【运单号】。";
      }
      return undefined;
    },
  },
};

/**
 * 必填槽位映射表 (向后兼容导出)
 */
export const REQUIRED_SLOTS_MAP: Record<string, string[]> = {
  [AgentIntentType.ORDER_MODIFY_ADDRESS]: ["orderId", "newAddress"],
  [AgentIntentType.ORDER_RETURN]: ["orderId"],
  [AgentIntentType.ORDER_CANCEL]: ["orderId"],
  [AgentIntentType.ORDER_QUERY]: ["orderId"],
};

/**
 * 🎯 实体抽取与槽位对齐引擎 (Entity & Slot Alignment Engine)
 */
export class SlotExtractor {
  public static readonly ORDER_ID_REGEX = EntityExtractors.ORDER_ID_REGEX;
  public static readonly ADDRESS_KEYWORDS_REGEX =
    EntityExtractors.ADDRESS_KEYWORDS_REGEX;
  public static readonly PROVINCE_CITY_REGEX =
    EntityExtractors.PROVINCE_CITY_REGEX;

  /**
   * 纯实体识别提取器 (Pure Entity Extractor)
   */
  public static extractEntities(
    input: string,
    context?: SlotExtractionContext,
  ): Partial<OrderTaskSlots> {
    const text = input.trim();
    const entities: Partial<OrderTaskSlots> = {};

    const orderId = EntityExtractors.extractOrderId(text, context);
    if (orderId) entities.orderId = orderId;

    const newAddress = EntityExtractors.extractNewAddress(text);
    if (newAddress) entities.newAddress = newAddress;

    const returnReason = EntityExtractors.extractReturnReason(text);
    if (returnReason) entities.returnReason = returnReason;

    return entities;
  }

  /**
   * 意图规则匹配器
   */
  public static detectIntents(text: string): IntentRule[] {
    return INTENT_DETECTION_RULES.filter((rule) => {
      if (!rule.pattern.test(text)) return false;
      if (rule.negativePattern && rule.negativePattern.test(text)) return false;
      return true;
    });
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

    // 1. 意图判别：若传入上下文意图则锁定，否则由规则表解析最高置信度意图
    const matchedRules = this.detectIntents(text);
    const primaryMatched = matchedRules[0];

    let intentType = AgentIntentType.CHAT;
    let confidence = 0.9;

    if (activeIntentContext) {
      intentType = activeIntentContext as AgentIntentType;
      confidence = 0.95;
    } else if (primaryMatched) {
      // 特殊处理：泛查单（如“我的订单”）在顶层应归为 CHAT/通用查询，不强行进入 ORDER_QUERY
      if (
        primaryMatched.intent === AgentIntentType.ORDER_QUERY &&
        isGeneralOrderListQuery(text)
      ) {
        intentType = AgentIntentType.CHAT;
        confidence = 0.9;
      } else {
        intentType = primaryMatched.intent;
        confidence = primaryMatched.confidence;
      }
    }

    // 2. 槽位提取与多轮对齐
    const extractedEntities = this.extractEntities(text, context);
    const slots: OrderTaskSlots = {
      ...(existingSlots || {}),
      ...extractedEntities,
    };

    // 3. 基于 Schema 校验必填槽位
    const schema = INTENT_SCHEMAS[intentType];
    const missingSlots: string[] = [];

    if (schema) {
      for (const slotDef of schema.slots) {
        if (slotDef.isRequired(text) && !slots[slotDef.name]) {
          missingSlots.push(slotDef.name);
        }
      }
    }

    // 4. 调度 Schema 反问话术生成器
    const clarificationMessage =
      missingSlots.length > 0
        ? schema?.buildClarificationMessage?.(slots, missingSlots)
        : undefined;

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
    const detected = this.detectIntents(text);

    if (detected.length <= 1) {
      return [this.extract(input, activeIntentContext, existingSlots, context)];
    }

    return detected.map((rule) =>
      this.extract(input, rule.intent, existingSlots, context),
    );
  }
}
