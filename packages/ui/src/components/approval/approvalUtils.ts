import type { Approval } from "types";

export type ApprovalCategory = "refund" | "address" | "human" | "generic";
export type RiskLevel = "critical" | "high" | "medium" | "low";

export interface ApprovalContextData {
  category: ApprovalCategory;
  orderId?: string;
  refundAmount?: number | string;
  oldAddress?: string;
  newAddress?: string;
  recipientName?: string;
  phone?: string;
  reason?: string;
  userInput?: string;
  triggerSource?: string;
  extraArgs: Record<string, unknown>;
}

export interface TriggerDiagnosis {
  category: ApprovalCategory;
  riskLevel: RiskLevel;
  title: string;
  triggerCause: string;
  ruleDescription: string;
  policyCode: string;
  targetOrderId?: string;
  diff?: Record<string, unknown>;
  rawPayload: Record<string, unknown>;
}

export function getApprovalCategory(actionType?: string): ApprovalCategory {
  if (!actionType) return "generic";
  const lower = actionType.toLowerCase();

  if (
    lower.includes("refund") ||
    lower.includes("processrefund") ||
    lower.includes("order_refund")
  ) {
    return "refund";
  }

  if (
    lower.includes("address") ||
    lower.includes("changeshippingaddress") ||
    lower.includes("modify_address") ||
    lower.includes("shipping")
  ) {
    return "address";
  }

  if (
    lower.includes("human") ||
    lower.includes("escalat") ||
    lower.includes("transfer")
  ) {
    return "human";
  }

  return "generic";
}

export function getApprovalContextData(
  approval: Approval,
): ApprovalContextData {
  const category = getApprovalCategory(approval.actionType);
  const payload = (approval.actionPayload || {}) as Record<string, unknown>;
  const args = ((payload.args as Record<string, unknown>) || {}) as Record<
    string,
    unknown
  >;

  const orderId =
    (payload.orderId as string) ||
    (args.orderId as string) ||
    (args.order_id as string) ||
    undefined;

  const refundAmount =
    (payload.refundAmount as number | string) ||
    (payload.amount as number | string) ||
    (args.refundAmount as number | string) ||
    (args.amount as number | string) ||
    undefined;

  const oldAddress =
    (payload.oldAddress as string) ||
    (payload.previousAddress as string) ||
    (args.oldAddress as string) ||
    (args.previousAddress as string) ||
    undefined;

  const newAddress =
    (payload.newAddress as string) ||
    (payload.address as string) ||
    (args.newAddress as string) ||
    (args.address as string) ||
    undefined;

  const recipientName =
    (payload.recipientName as string) ||
    (payload.recipient as string) ||
    (args.recipientName as string) ||
    (args.recipient as string) ||
    (args.name as string) ||
    undefined;

  const phone =
    (payload.phone as string) ||
    (payload.telephone as string) ||
    (args.phone as string) ||
    (args.telephone as string) ||
    undefined;

  const reason =
    approval.reason ||
    (payload.reason as string) ||
    (payload.rejectionReason as string) ||
    (args.reason as string) ||
    (payload.description as string) ||
    undefined;

  const userInput =
    (payload.userInput as string) ||
    (payload.userMessage as string) ||
    (args.userInput as string) ||
    (args.userMessage as string) ||
    undefined;

  const triggerSource =
    (payload.triggerSource as string) ||
    (args.triggerSource as string) ||
    undefined;

  const extractedKeys = new Set([
    "orderId",
    "order_id",
    "refundAmount",
    "amount",
    "oldAddress",
    "previousAddress",
    "newAddress",
    "address",
    "recipientName",
    "recipient",
    "name",
    "phone",
    "telephone",
    "reason",
    "userInput",
    "userMessage",
    "triggerSource",
    "description",
  ]);

  const extraArgs: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(args)) {
    if (!extractedKeys.has(k) && v !== undefined && v !== null) {
      extraArgs[k] = v;
    }
  }

  return {
    category,
    orderId,
    refundAmount,
    oldAddress,
    newAddress,
    recipientName,
    phone,
    reason,
    userInput,
    triggerSource,
    extraArgs,
  };
}

// 🧠 精细化的人工转接原因归因器
function resolveHumanEscalationCause(context: ApprovalContextData): string {
  if (context.reason) return context.reason;

  const src = context.triggerSource?.toLowerCase() || "";
  const input = context.userInput || "";

  if (
    src.includes("sentiment") ||
    /(态度|生气|投诉|太差|听不懂|垃圾)/i.test(input)
  ) {
    return "【情绪风控拦截】检测到用户负面情绪波动或强烈不满，系统主动挂起并升级至资深客服";
  }
  if (
    src.includes("circuit") ||
    src.includes("retry") ||
    /(重试|失败|一直报错)/i.test(input)
  ) {
    return "【连续重试熔断】多次意图识别或工具执行未达预期，触发智能熔断保护转人工";
  }
  if (/(人工|真人|客服|专员|人工台)/i.test(input)) {
    return "【用户主动诉求】用户明确要求转接真人客服专员提供一对一支持";
  }
  return "【智能分流升级】多轮意图交互未闭环，系统触发主动协同人工接管";
}

// 🛡️ 策略分发诊断字典 (Open-Closed Principle)
const DIAGNOSIS_STRATEGIES: Record<
  ApprovalCategory,
  (ctx: ApprovalContextData, raw: Record<string, unknown>) => TriggerDiagnosis
> = {
  refund: (ctx, raw) => ({
    category: "refund",
    riskLevel: "critical",
    title: "🚨 资金退款安全红线拦截 (Refund Security Gate)",
    triggerCause:
      ctx.reason ||
      `拟退款金额 ${ctx.refundAmount ? `¥${Number(ctx.refundAmount).toFixed(2)}` : ""} 超过商户自动放行限额`,
    ruleDescription:
      "SOP 财务准则：单笔退款高于放行阈值或订单处于已发货/结算期，必须由人工管理员二次授权。",
    policyCode: "SEC-FIN-001",
    targetOrderId: ctx.orderId,
    diff: { refundAmount: ctx.refundAmount },
    rawPayload: raw,
  }),

  address: (ctx, raw) => ({
    category: "address",
    riskLevel: "high",
    title: "🚚 关键配送地址变更拦截 (Address Modification Gate)",
    triggerCause:
      ctx.reason ||
      "订单已处于分拣/出库关键节点，修改跨省市地址存在物流窜货与冒领风险",
    ruleDescription:
      "SOP 履约准则：出库后改派地址需人工核验运费差价并向承运物流商发起物理拦截。",
    policyCode: "SEC-LOG-002",
    targetOrderId: ctx.orderId,
    diff: {
      oldAddress: ctx.oldAddress,
      newAddress: ctx.newAddress,
      recipientName: ctx.recipientName,
      phone: ctx.phone,
    },
    rawPayload: raw,
  }),

  human: (ctx, raw) => ({
    category: "human",
    riskLevel: "medium",
    title: "🎧 人工客服实时接管工单 (Human Support Escalation)",
    triggerCause: resolveHumanEscalationCause(ctx),
    ruleDescription:
      "SOP 体验准则：当检测到强诉求或情绪升级时，AI 助理立即挂起，交由坐席专家一对一处理。",
    policyCode: "SEC-SVC-003",
    targetOrderId: ctx.orderId,
    diff: ctx.userInput ? { 用户原话: ctx.userInput } : undefined,
    rawPayload: raw,
  }),

  generic: (ctx, raw) => ({
    category: "generic",
    riskLevel: "low",
    title: `🛡️ 敏感高权限动作核签 [${(raw.actionType as string) || "未知动作"}]`,
    triggerCause:
      ctx.reason || "调起外部未配置免密放行策略的操作，触发系统安全复核",
    ruleDescription:
      "SOP 权限准则：涉及物理数据库变更或第三方 API 调用的高危操作需人工复核。",
    policyCode: "SEC-GEN-099",
    targetOrderId: ctx.orderId,
    rawPayload: raw,
  }),
};

export function diagnoseApprovalTrigger(approval: Approval): TriggerDiagnosis {
  const context = getApprovalContextData(approval);
  const rawPayload = (approval.actionPayload || {}) as Record<string, unknown>;
  const strategy =
    DIAGNOSIS_STRATEGIES[context.category] || DIAGNOSIS_STRATEGIES.generic;
  return strategy(context, rawPayload);
}
