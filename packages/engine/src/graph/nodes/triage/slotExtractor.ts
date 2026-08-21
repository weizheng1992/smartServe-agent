import {
  AgentIntentType,
  type AgentTaskSpec,
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

export class SlotExtractor {
  private static readonly ORDER_ID_REGEX =
    /(?:ORD(?:[-_][A-Z0-9]+)+|\b[A-Z]{2,4}[-_]?\d{4,}\b|\b\d{8,}\b)/i;

  private static readonly ADDRESS_KEYWORDS_REGEX =
    /(?:改成|改到|送至|送往|送去|寄到|寄往|新地址[是为:：]?|地址[是为:：])\s*([^,，!！?？\n]+)/i;

  private static readonly PROVINCE_CITY_REGEX =
    /(?:北京市|上海市|天津市|重庆市|广东省|浙江省|江苏省|四川省|湖北省|山东省|河南省|河北省|陕西省|福建省|湖南省|安徽省|辽宁省|江西省|广西|海南省|贵州省|云南省|山西省|吉林省|黑龙江省|内蒙古|新疆|西藏|青海|宁夏|海淀区|朝阳区|西城区|东城区|浦东新区|黄浦区|徐汇区|静安区)[^\s,，。!！?？]+/i;

  /**
   * 结构化槽位与意图抽取器
   */
  public static extract(
    input: string,
    activeIntentContext?: string,
    existingSlots?: OrderTaskSlots,
  ): AgentTaskSpec {
    const text = input.trim();
    const textLower = text.toLowerCase();

    // 1. 意图判别 (L1 快速规则层)
    let intentType: AgentIntentType = AgentIntentType.CHAT;
    let confidence = 0.9;

    const isModifyAddress =
      /(?:修改|更改|变更|换|改|更新).*?(?:收货)?(?:地址|位置|地方)/i.test(
        text,
      ) ||
      /(?:收货)?(?:地址|位置|地方).*?(?:修改|更改|变更|换|改|错|变)/i.test(
        text,
      ) ||
      /改派/i.test(text);

    const isReturnOrRefund = /(?:退货|退款|退单|申请售后|退钱|不想要了)/i.test(
      text,
    );

    const isCancelOrder = /(?:取消订单|撤销订单|退订)/i.test(text);

    const isOrderQuery =
      /(?:查物流|物流到哪|物流信息|快递单号|快递到哪|发货了吗|包裹到哪)/i.test(
        text,
      ) ||
      (/(?:查订单|查下订单|查询订单)/i.test(text) &&
        this.ORDER_ID_REGEX.test(text));

    const isMetricQuery =
      /(?:销售额|销量|出货量|毛利|利润率|gmv|滞销|排行|最卖钱|最赚钱)/i.test(
        text,
      );

    if (isModifyAddress) {
      intentType = AgentIntentType.ORDER_MODIFY_ADDRESS;
      confidence = 0.95;
    } else if (isReturnOrRefund) {
      intentType = AgentIntentType.ORDER_RETURN;
      confidence = 0.95;
    } else if (isCancelOrder) {
      intentType = AgentIntentType.ORDER_CANCEL;
      confidence = 0.92;
    } else if (isOrderQuery) {
      intentType = AgentIntentType.ORDER_QUERY;
      confidence = 0.92;
    } else if (isMetricQuery) {
      intentType = AgentIntentType.METRIC_QUERY;
      confidence = 0.96;
    } else if (activeIntentContext) {
      // 继承上下文中的进行中意图 (Multi-turn slot filling)
      intentType = activeIntentContext as AgentIntentType;
      confidence = 0.85;
    }

    // 2. 槽位提取 (Slot Extraction)
    const slots: OrderTaskSlots = {
      ...(existingSlots || {}),
    };

    // 提取 orderId
    const orderMatch = text.match(this.ORDER_ID_REGEX);
    if (orderMatch && orderMatch[0]) {
      slots.orderId = orderMatch[0].toUpperCase();
    }

    // 提取 newAddress
    if (
      intentType === AgentIntentType.ORDER_MODIFY_ADDRESS ||
      activeIntentContext === AgentIntentType.ORDER_MODIFY_ADDRESS
    ) {
      const addrKwMatch = text.match(this.ADDRESS_KEYWORDS_REGEX);
      if (addrKwMatch && addrKwMatch[1]) {
        slots.newAddress = addrKwMatch[1].trim();
      } else {
        const provMatch = text.match(this.PROVINCE_CITY_REGEX);
        if (provMatch && provMatch[0]) {
          slots.newAddress = provMatch[0].trim();
        }
      }
    }

    // 提取 returnReason
    if (
      intentType === AgentIntentType.ORDER_RETURN ||
      activeIntentContext === AgentIntentType.ORDER_RETURN
    ) {
      if (
        text.includes("尺码") ||
        text.includes("穿不上") ||
        text.includes("大") ||
        text.includes("小")
      ) {
        slots.returnReason = "wrong_size";
      } else if (
        text.includes("质量") ||
        text.includes("坏") ||
        text.includes("破") ||
        text.includes("瑕疵")
      ) {
        slots.returnReason = "quality_issue";
      } else if (
        text.includes("不符合") ||
        text.includes("不一样") ||
        text.includes("虚假")
      ) {
        slots.returnReason = "not_as_described";
      } else if (
        text.includes("七天") ||
        text.includes("不喜欢") ||
        text.includes("不想要")
      ) {
        slots.returnReason = "no_reason_7d";
      }
    }

    // 3. 计算缺失槽位 (Missing Slots)
    const required = REQUIRED_SLOTS_MAP[intentType] || [];
    const missingSlots: string[] = [];

    for (const reqSlot of required) {
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
}
