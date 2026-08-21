import type { QuickRepliesData, QuickReplyOption } from "types";

export interface EnumOptionItem {
  value: string;
  label: string;
  description?: string;
  icon?: string;
  promptText?: string;
}

export interface SlotDefinition<T = string> {
  name: string;
  label: string;
  type: "string" | "number" | "boolean" | "enum";
  defaultValue: T;
  enumOptions?: EnumOptionItem[];
  clarificationPrompt?: string;
  synonyms?: Record<string, string[]>; // e.g. { gmv: ["销售额", "卖得好", "流水", "业绩"], volume: ["销量", "卖得多", "出货量", "件数"], gross_profit: ["利润", "赚钱", "毛利", "毛利润"] }
}

export interface ResolvedSlotResult<T = string> {
  slotName: string;
  resolvedValue: T;
  isDefaultFallback: boolean;
  isExplicitlyMentioned: boolean;
  matchedSynonym?: string;
  quickReplies?: QuickRepliesData;
  clarificationMessage?: string;
}

/**
 * 🌟 通用声明式槽位消歧与模糊指令解析引擎 (Generic Slot Disambiguation & Resolution Engine)
 */
export class SlotDisambiguationEngine {
  /**
   * 通用解析单个槽位，自动处理：模糊同义词匹配 -> 用户个性化记忆覆盖 -> Default 缺省兜底 -> 动态生成消歧切换卡片
   */
  public static resolveSlot<T extends string>(
    input: string,
    slotDef: SlotDefinition<T>,
    userPreferenceValue?: T,
  ): ResolvedSlotResult<T> {
    const cleanInput = input.trim().toLowerCase();
    let matchedValue: T | undefined;
    let matchedSynonym: string | undefined;
    let isExplicit = false;

    // 1. 先匹配同义词表 (Synonyms Pattern Matching)
    if (slotDef.synonyms) {
      for (const [val, synonymList] of Object.entries(slotDef.synonyms)) {
        for (const syn of synonymList) {
          if (cleanInput.includes(syn.toLowerCase())) {
            matchedValue = val as T;
            matchedSynonym = syn;
            isExplicit = true;
            break;
          }
        }
        if (matchedValue) break;
      }
    }

    // 2. 再匹配 Enum 本身的 Label 或 Value
    if (!matchedValue && slotDef.enumOptions) {
      for (const opt of slotDef.enumOptions) {
        if (
          cleanInput.includes(opt.label.toLowerCase()) ||
          cleanInput.includes(opt.value.toLowerCase())
        ) {
          matchedValue = opt.value as T;
          matchedSynonym = opt.label;
          isExplicit = true;
          break;
        }
      }
    }

    // 3. 若未明确匹配，优先查看用户记忆画像偏好 (User Long-Memory Preference)
    if (!matchedValue && userPreferenceValue) {
      matchedValue = userPreferenceValue;
      isExplicit = false;
    }

    // 4. 仍未匹配，采用声明式 Default 兜底
    const isDefault = !matchedValue;
    const finalValue: T = matchedValue || slotDef.defaultValue;

    // 5. 动态为其他可选维度构造一键纠偏胶囊 (Zero-Code Dynamic Quick Replies)
    let quickReplies: QuickRepliesData | undefined;
    if (slotDef.enumOptions && slotDef.enumOptions.length > 1) {
      const options: QuickReplyOption[] = slotDef.enumOptions.map((opt) => ({
        label: `${opt.icon || "📊"} 按${opt.label}排行`,
        action: "send_message",
        payload: {
          text: opt.promptText || `按${opt.label}查询商品排行`,
          metric: opt.value,
        },
      }));

      quickReplies = {
        title:
          slotDef.clarificationPrompt ||
          `您也可以一键切换不同${slotDef.label}统计：`,
        options,
      };
    }

    const currentOpt = slotDef.enumOptions?.find((o) => o.value === finalValue);
    const clarificationMessage = isDefault
      ? `（未指定${slotDef.label}，已默认按【${currentOpt?.label || String(finalValue)}】为您执行统计）`
      : undefined;

    return {
      slotName: slotDef.name,
      resolvedValue: finalValue,
      isDefaultFallback: isDefault,
      isExplicitlyMentioned: isExplicit,
      matchedSynonym,
      quickReplies,
      clarificationMessage,
    };
  }
}

/**
 * 📦 常用业务槽位声明规范 (Pre-configured Business Slots)
 */
export const PRODUCT_RANKING_METRIC_SLOT: SlotDefinition<
  "gmv" | "volume" | "gross_profit"
> = {
  name: "rankingMetric",
  label: "统计指标",
  type: "enum",
  defaultValue: "gmv",
  clarificationPrompt: "您也可以一键切换不同排序维度：",
  enumOptions: [
    {
      value: "gmv",
      label: "总销售额 (GMV)",
      description: "商品销售流水总金额最高",
      icon: "💰",
      promptText: "按总销售额最高查询我负责的商品 Top 5",
    },
    {
      value: "volume",
      label: "出货销量 (件数)",
      description: "商品订单出库售出总件数最多",
      icon: "📦",
      promptText: "按出货销量最高查询我负责的商品 Top 5",
    },
    {
      value: "gross_profit",
      label: "净毛利润 (收益)",
      description: "销售总额减去进货成本后的实际利润最高",
      icon: "📈",
      promptText: "按净毛利润最高查询我负责的商品 Top 5",
    },
  ],
  synonyms: {
    gmv: ["销售额", "卖得好", "流水", "业绩", "收入", "最卖钱", "成交额"],
    volume: ["销量", "卖得多", "出货量", "件数", "爆款", "走量", "单数"],
    gross_profit: ["利润", "赚钱", "毛利", "毛利润", "净利", "赚得多", "收益"],
  },
};
