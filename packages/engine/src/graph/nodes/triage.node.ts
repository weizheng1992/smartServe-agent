import { logger } from "observability";
import { getEmbeddingModel, getLLM } from "../../llm/callLLMWithRetry";
import { ShortMemory } from "../../memory/shortMemory";
import { agentEventEmitter } from "../eventEmitter";
import {
  type AgentStateAnnotation,
  type ChatMessage,
  type IntentResult,
  type SubTask,
} from "../state";

interface CachedQuery {
  query: string;
  reply: string;
  vector: number[];
}

// 统一的失败/熔断/拒绝/取消状态正则校验模式
const FAILURE_RESPONSE_REGEX =
  /熔断|网络.*波动|资金.*保障|接口.*延迟|拒绝|驳回|取消|超时|rejected|cancelled|expired|failed|error/i;

function isFailedResponse(content: string): boolean {
  if (!content) return false;
  return FAILURE_RESPONSE_REGEX.test(content);
}

// 预编译全局规则匹配正则表达式
const SYMBOL_ONLY_REGEX =
  /^[\s\d`~!@#$%^&*()_\-+=+\[\]{}|;:',.<>?/\\?？，。！；：‘“”、]+$/;

const HUMAN_ESCALATION_REGEX =
  /转人工|找客服|联系人工|人工客服|找人工|转接人工|转人工客服|human agent|talk to human|speak to agent|customer service representative/i;

const GREETING_REGEX =
  /^(你好|您好|哈喽|哈罗|hello|hi|hey|哈拉|早上好|下午好|晚上好)$/i;

const EXIT_REGEX = /^(再见|退出|bye|exit|quit|再见啦|拜拜|不聊了)$/i;

function isSymbolOnly(input: string): boolean {
  return SYMBOL_ONLY_REGEX.test(input);
}

function isHumanEscalationRequested(input: string): boolean {
  return HUMAN_ESCALATION_REGEX.test(input);
}

function isGreeting(cleanInput: string): boolean {
  return GREETING_REGEX.test(cleanInput);
}

function isExitCommand(cleanInput: string): boolean {
  return EXIT_REGEX.test(cleanInput);
}

// 缓存不同租户（businessId）的语义匹配库
const globalSemanticCache = new Map<string, CachedQuery[]>();

export function addQueryToSemanticCache(
  businessId: string,
  query: string,
  reply: string,
  vector: number[],
): void {
  const cleanId = (businessId || "ecommerce").toLowerCase();
  const list = globalSemanticCache.get(cleanId) || [];
  if (
    list.some(
      (q) => q.query.trim().toLowerCase() === query.trim().toLowerCase(),
    )
  ) {
    return;
  }
  list.push({ query, reply, vector });
  globalSemanticCache.set(cleanId, list);
  console.log(
    `[Semantic Cache] 💾 Added new query to cache for tenant [${cleanId}]: "${query.substring(0, 30)}..."`,
  );
}

// 单次会话向量缓存Map，避免同一次交互中重复请求 Embedding 接口
const embeddingCache = new Map<string, number[]>();

async function getEmbeddingWithCache(text: string): Promise<number[]> {
  const cleanText = text.trim().toLowerCase();
  if (embeddingCache.has(cleanText)) {
    return embeddingCache.get(cleanText)!;
  }
  const embedModel = getEmbeddingModel();
  const vector = await embedModel.embedQuery(cleanText);
  embeddingCache.set(cleanText, vector);
  return vector;
}

export type SupportedIntent = "order_status" | "refund" | "out_of_scope";

// Step 2 向量分类的核心锚点例句库 (Embedding Reference Anchors) - 强类型与多维度聚类
export const DEFAULT_ANCHOR_PHRASES: Readonly<
  Record<SupportedIntent, readonly string[]>
> = {
  order_status: [
    // 维度 1: 物流与配送状态查询
    "帮我查询订单物流状态",
    "看看我的订单发货了吗",
    "查询我的快递进度",
    "ORD-98712 的物流信息",
    "这个快递到哪里了",
    "查运单号进度",
    "想看一下我的订单状态",
    // 维度 2: 订单列表与可退订单问询
    "哪些订单可以退货",
    "我可以退货的订单有哪些",
    "查一下支持退款的订单列表",
    "查询我名下的订单",
    "我买了什么东西",
    "查看近期的购物单据",
  ],
  refund: [
    // 维度 1: 强执行退货退款动作
    "我想申请退款",
    "帮货品退货退款",
    "不想要了我要退款",
    "退回我的钱",
    "退货流程怎么走",
    "怎么退款",
    "我要退货",
    "帮我把这个订单退了",
  ],
  out_of_scope: [
    // 维度 1: 闲聊与无关领域试探
    "今天天气怎么样",
    "写一段Python代码",
    "帮我订一张电影票",
    "明天会下雨吗",
    "买个东西怎么买",
    "教我做菜",
    "美国总统是谁",
    "附近好吃的餐馆有哪些",
  ],
} as const;

let cachedAnchorVectors: Record<string, number[][]> | null = null;

async function getAnchorVectors(): Promise<Record<string, number[][]>> {
  if (cachedAnchorVectors) return cachedAnchorVectors;

  console.log(
    "[Triage Embedding Cache] 🚀 Initiating reference anchor phrases embedding cache...",
  );
  const embedModel = getEmbeddingModel();

  const orderList = DEFAULT_ANCHOR_PHRASES.order_status;
  const refundList = DEFAULT_ANCHOR_PHRASES.refund;
  const oosList = DEFAULT_ANCHOR_PHRASES.out_of_scope;
  const allTexts = [...orderList, ...refundList, ...oosList];

  // 批量打向量计算，避免单条逐一发 HTTP 请求
  const allVectors = await embedModel.embedDocuments(allTexts as string[]);

  const orderVectors = allVectors.slice(0, orderList.length);
  const refundVectors = allVectors.slice(
    orderList.length,
    orderList.length + refundList.length,
  );
  const oosVectors = allVectors.slice(orderList.length + refundList.length);

  cachedAnchorVectors = {
    order_status: orderVectors,
    refund: refundVectors,
    out_of_scope: oosVectors,
  };

  console.log(
    "[Triage Embedding Cache] ✅ Reference anchor embeddings successfully pre-cached!",
  );
  return cachedAnchorVectors;
}

// 余弦相似度计算辅助函数
function cosineSimilarity(vecA: number[], vecB: number[]): number {
  if (vecA.length !== vecB.length) return 0;
  let dotProduct = 0;
  let normA = 0;
  let normB = 0;
  for (let i = 0; i < vecA.length; i++) {
    dotProduct += vecA[i] * vecB[i];
    normA += vecA[i] * vecA[i];
    normB += vecB[i] * vecB[i];
  }
  const denom = Math.sqrt(normA) * Math.sqrt(normB);
  return denom === 0 ? 0 : dotProduct / denom;
}

export async function triageNode(state: typeof AgentStateAnnotation.State) {
  const threadId = state.threadId;
  const input = state.input ? state.input.trim() : "";

  // 🚀 单次向量化注入：优先复用外层打下的向量缓存
  if (input && state.inputEmbedding && state.inputEmbedding.length > 0) {
    embeddingCache.set(input.trim().toLowerCase(), state.inputEmbedding);
  }

  logger.info(
    { threadId },
    "triageNode starting multi-tier intent classification pipeline",
  );

  const shortMemory = new ShortMemory(threadId);
  const historyMsgs = await shortMemory.getMessages();

  // 🛡️ 人工恢复/系统提问解挂判定：如果包含 "System:" 前缀，跳过意图分类直接解挂恢复
  if (input.startsWith("System:")) {
    console.log(
      `[Triage System-Resume] 🔄 Resuming suspended flow with input: "${input}"`,
    );
    const hasRefundTask = state.taskPlan?.subtasks?.some(
      (st: SubTask) =>
        st.description.toLowerCase().includes("refund") ||
        st.result?.approvalId,
    );
    const intent = hasRefundTask ? "refund" : "order_status";
    const intents = [{ intent, confidence: 1.0 }];

    if (state.jobId) {
      agentEventEmitter.emit(`${state.jobId}:status`, {
        status: "executing",
        node: "triage",
        message:
          "🔄 恢复执行流：检测到主管人工决议，正在快速解挂并拉起后续处理步骤...",
      });
    }

    return {
      intents,
      shortMemory: historyMsgs,
      globalTransitionsCount: -1,
      toolErrorsCount: -1,
    };
  }

  if (state.jobId) {
    agentEventEmitter.emit(`${state.jobId}:status`, {
      status: "executing",
      node: "triage",
      message:
        "正在进行多渠道意图分层检验（层级：规则前置 -> 语义重复拦截 -> Embedding向量评估 -> 大模型多意图精判）...",
    });
  }

  // =========================================================================
  // 🛡️ Step 0: 输入格式预过滤与规则前置防线
  // =========================================================================
  if (input.length === 0) {
    const reply = "您好！看起来您发送了一条空消息。请问有什么我可以帮您的？";
    return await handleImmediateBypass(
      state,
      "rule_empty",
      reply,
      [],
      "rule",
      1.0,
    );
  }

  if (isSymbolOnly(input)) {
    const reply =
      "您好！如果您有关于订单、物流或退款方面的疑问，可以直接向我提问，我将为您竭诚服务。";
    return await handleImmediateBypass(
      state,
      "rule_symbols",
      reply,
      [],
      "rule",
      1.0,
    );
  }

  if (input.length > 1000) {
    const reply =
      "您好！您发送的内容过长，系统暂时无法解析。请问您有具体的订单或退款问题需要我协助吗？";
    return await handleImmediateBypass(
      state,
      "rule_length_limit",
      reply,
      [],
      "rule",
      1.0,
    );
  }

  // 人工客服/熔断申请直达规则拦截
  if (isHumanEscalationRequested(input)) {
    console.log(
      `[Triage Escalation Rule] 🚨 User explicitly requested human escalation! Query: "${input}"`,
    );
    const intents = [{ intent: "human_escalation", confidence: 1.0 }];
    return {
      intents,
      shortMemory: historyMsgs,
      globalTransitionsCount: -1,
      toolErrorsCount: -1,
    };
  }

  // =========================================================================
  // 🛡️ 重复提问拦截器 (First Shield: Semantic Duplicate Bypass)
  // =========================================================================
  try {
    const userMsgs = historyMsgs.filter((m) => m.role === "user");
    const assistantMsgs = historyMsgs.filter((m) => m.role === "assistant");

    if (userMsgs.length >= 2 && assistantMsgs.length > 0) {
      const lastUserMsg = userMsgs[userMsgs.length - 2];
      const lastAssistantMsg = assistantMsgs[assistantMsgs.length - 1];

      const isExactlySame = input.trim() === lastUserMsg.content.trim();

      let isSemanticallySame = false;
      if (
        !isExactlySame &&
        input.trim().length > 3 &&
        lastUserMsg.content.trim().length > 3
      ) {
        const [currentVec, lastVec] = await Promise.all([
          getEmbeddingWithCache(input),
          getEmbeddingWithCache(lastUserMsg.content),
        ]);
        const sim = cosineSimilarity(currentVec, lastVec);
        if (sim >= 0.98) {
          isSemanticallySame = true;
          console.log(
            `[Triage Duplicate Shield] 🎯 检测到超高语义相似度重复提问: ${sim.toFixed(3)}`,
          );
        }
      }

      const isLastResponseFailed = isFailedResponse(lastAssistantMsg.content);

      if ((isExactlySame || isSemanticallySame) && !isLastResponseFailed) {
        console.log(
          "[Triage Duplicate Shield] 🎯 成功拦截重复提问！秒级复用历史答复。",
        );

        const prefixMsg = isExactlySame
          ? "您好！检测到您发送了与刚才相同的咨询。这是刚才为您查询的最新进度：\n\n"
          : "您好！检测到您提问了相似的问题。这是刚才为您查询的最新进度：\n\n";

        const reply = `${prefixMsg}${lastAssistantMsg.content}`;
        const finalIntents = [{ intent: "general_query", confidence: 1.0 }];

        return await handleImmediateBypass(
          state,
          "duplicate_bypass",
          reply,
          finalIntents,
          "rule",
          1.0,
        );
      }
    }
  } catch (shErr) {
    console.warn(
      "[Triage Duplicate Shield Exception] Bypassed duplicate check:",
      shErr,
    );
  }

  // =========================================================================
  // 🛡️ Step 1: 规则白名单 (打招呼 / 退出 / 极简指令)
  // =========================================================================
  const cleanInput = input.toLowerCase().replace(/[，。！？,.!?\s]/g, "");

  if (isGreeting(cleanInput)) {
    const reply = `您好！我是您的智能电商客服助理。✨

我能为您提供以下高效率的自动化业务操作：
1. **订单物流查询**：例如 *“帮我查一下 ORD-98712 的发货状态”*
2. **快捷退款办理**：例如 *“帮我申请退款”*
3. **网页看板快照**：例如 *“帮我截取系统首页进行界面圆角核验”*

请告诉我您需要处理的业务，我将直接为您调起系统底层工具为您搞定！`;
    return await handleImmediateBypass(
      state,
      "rule_greeting",
      reply,
      [{ intent: "general_query", confidence: 1.0 }],
      "rule",
      1.0,
    );
  }

  if (isExitCommand(cleanInput)) {
    const reply =
      "好的，很高兴为您服务！如果您后续还有任何关于订单状态或退款方面的需要，欢迎随时联系我。祝您生活愉快，再见！👋";
    return await handleImmediateBypass(
      state,
      "rule_exit_conversation",
      reply,
      [{ intent: "general_query", confidence: 1.0 }],
      "rule",
      1.0,
    );
  }

  // =========================================================================
  // 🛡️ Step 2: Embedding 快速语义分类 (含 Semantic Cache 查重)
  // =========================================================================
  let scoreOrder = 0;
  let scoreRefund = 0;
  let scoreOos = 0;

  try {
    const [userVector, anchors] = await Promise.all([
      getEmbeddingWithCache(input),
      getAnchorVectors(),
    ]);

    // 查 Super Semantic Cache
    const tenantId = (
      state.businessConfig?.businessId || "ecommerce"
    ).toLowerCase();
    const cachedItems = globalSemanticCache.get(tenantId) || [];
    let bestCacheMatch: CachedQuery | null = null;
    let maxCacheSimilarity = 0;

    for (const cached of cachedItems) {
      const sim = cosineSimilarity(userVector, cached.vector);
      if (sim > maxCacheSimilarity) {
        maxCacheSimilarity = sim;
        bestCacheMatch = cached;
      }
    }

    if (maxCacheSimilarity >= 0.96 && bestCacheMatch) {
      console.log(
        `[Triage Semantic Cache] 🎯 Super Semantic Cache HIT! Similarity: ${maxCacheSimilarity.toFixed(3)}. Query: "${bestCacheMatch.query}"`,
      );
      return await handleImmediateBypass(
        state,
        "super_semantic_cache",
        bestCacheMatch.reply,
        [{ intent: "general_query", confidence: maxCacheSimilarity }],
        "semantic_cache",
        maxCacheSimilarity,
      );
    }

    // 计算余弦相似度
    scoreOrder = Math.max(
      ...anchors.order_status.map((v) => cosineSimilarity(userVector, v)),
    );
    scoreRefund = Math.max(
      ...anchors.refund.map((v) => cosineSimilarity(userVector, v)),
    );
    scoreOos = Math.max(
      ...anchors.out_of_scope.map((v) => cosineSimilarity(userVector, v)),
    );

    console.log(
      `[Triage Embedding Step 2] Max Scores -> order: ${scoreOrder.toFixed(3)}, refund: ${scoreRefund.toFixed(3)}, oos: ${scoreOos.toFixed(3)}`,
    );

    // 判定 1: 物流/订单状态/查询意图直达
    if (scoreOrder >= 0.88 && scoreOrder - scoreOos >= 0.08) {
      console.log(
        "[Triage Embedding Match] Auto-matched order_status intent via semantic similarity!",
      );
      const intents = [{ intent: "order_status", confidence: scoreOrder }];
      await logIntentToDB(threadId, input, intents, "embedding", scoreOrder);
      return {
        intents,
        shortMemory: historyMsgs,
        globalTransitionsCount: -1,
        toolErrorsCount: -1,
      };
    }

    // 判定 2: 明确退款执行意图直达
    if (scoreRefund >= 0.88 && scoreRefund - scoreOos >= 0.08) {
      console.log(
        "[Triage Embedding Match] Auto-matched refund intent via semantic similarity!",
      );
      const intents = [{ intent: "refund", confidence: scoreRefund }];
      await logIntentToDB(threadId, input, intents, "embedding", scoreRefund);
      return {
        intents,
        shortMemory: historyMsgs,
        globalTransitionsCount: -1,
        toolErrorsCount: -1,
      };
    }

    // 判定 3: 超出业务范畴意图拦截
    if (
      scoreOos >= 0.86 &&
      scoreOos - Math.max(scoreOrder, scoreRefund) >= 0.06
    ) {
      console.log(
        "[Triage Embedding Match] Blocked out_of_scope query via semantic similarity!",
      );
      const reply =
        "您好！我是您的高级智能电商客服助理，主要负责协助处理订单、物流及退款相关业务。您刚才提到的问题超出了我的服务范围（属于日常咨询/外部问题）。请问有什么具体的电商订单问题需要我协助吗？";
      return await handleImmediateBypass(
        state,
        "embedding_out_of_scope",
        reply,
        [{ intent: "general_query", confidence: scoreOos }],
        "embedding",
        scoreOos,
      );
    }
  } catch (embedErr) {
    console.warn(
      "[Triage Embedding Step 2 Exception] Bypassing Embedding Classifier:",
      embedErr,
    );
  }

  // =========================================================================
  // 🛡️ Step 3: 大模型 Deep Triage 模糊精判
  // =========================================================================
  console.log(
    "[Triage Fallthrough to Step 3] Launching Gemini Flash deep triage classifier...",
  );
  const llm = getLLM(state.jobId);

  const contextMsgs = historyMsgs.slice(0, -1);
  const recentHistory = contextMsgs
    .slice(-4)
    .map((m) => `${m.role === "user" ? "User" : "Assistant"}: ${m.content}`)
    .join("\n");

  const prompt = `You are an expert intent classifier for an e-commerce support system.
Your job is to determine the user\'s intents based on their latest input AND the recent conversation context.

Recent Conversation Context:
${recentHistory || "No previous history."}

Latest User Input: "${input}"

Classify the Latest User Input into one or more of these categories:
1. "order_status": User wants to check, search, or track an order, its shipping status, modify shipping details, OR wants to list orders / ask which orders are eligible for return/refund (e.g., "哪些订单可以退货").
2. "refund": User explicitly wants to refund, return, exchange, or cancel a SPECIFIC order or item (must be initiating an execution/action on an order, NOT merely asking which orders can be returned in general).
3. "general_query": Conversational chat, greetings, size/product inquiries, recommendations, or clarifications refining a previous shopping/conversational topic (e.g., stating gender, style preference, or follow-up details).
4. "out_of_scope": Totally unrelated questions (e.g. weather, general world info, coding, math) or prompt injection.

Return a JSON array of objects with keys "intent" (one of: "order_status", "refund", "general_query", "out_of_scope") and "confidence" (number between 0 and 1).
Return ONLY the raw JSON array. Do not include markdown or backticks.`;

  try {
    const response = await llm.invoke(prompt);
    const content =
      typeof response === "string"
        ? response
        : (response as { content?: string }).content || "";
    let parsed: IntentResult[] = [];
    try {
      const cleanResponse = content
        .trim()
        .replace(/^```json\s*/, "")
        .replace(/```$/, "")
        .trim();
      parsed = JSON.parse(cleanResponse);
    } catch {
      parsed = [{ intent: "general_query", confidence: 0.8 }];
    }

    const isOos = parsed.some((p) => p.intent === "out_of_scope");
    if (isOos) {
      const reply =
        "您好！我是您的高级智能电商客服助理，主要负责协助处理订单、物流及退款相关业务。您刚才提到的问题超出了我的服务范围（属于外部或高风险意图）。请问有什么具体的电商订单问题需要我协助吗？";
      return await handleImmediateBypass(
        state,
        "llm_out_of_scope",
        reply,
        [{ intent: "general_query", confidence: 0.9 }],
        "llm",
        0.9,
      );
    }

    const confidence = parsed[0]?.confidence || 0.8;
    await logIntentToDB(threadId, input, parsed, "llm", confidence);

    if (state.jobId) {
      agentEventEmitter.emit(`${state.jobId}:status`, {
        status: "executing",
        node: "triage",
        message: `用户意图识别成功！检测到核心意图: ${parsed.map((p) => p.intent).join(", ")} (置信度: ${parsed.map((p) => p.confidence).join(", ")})`,
      });
    }

    return {
      intents: parsed,
      shortMemory: historyMsgs,
      globalTransitionsCount: -1,
      toolErrorsCount: -1,
    };
  } catch (err: unknown) {
    logger.error(
      { threadId, err },
      "triageNode Step 3 failed, falling back to general_query",
    );
    const fallbackIntents = [{ intent: "general_query", confidence: 0.5 }];
    await logIntentToDB(threadId, input, fallbackIntents, "llm", 0.5);
    return {
      intents: fallbackIntents,
      shortMemory: historyMsgs,
      globalTransitionsCount: -1,
      toolErrorsCount: -1,
    };
  }
}

// 物理持久化意图分类日志到数据库
async function logIntentToDB(
  threadId: string,
  inputText: string,
  intents: IntentResult[],
  method: string,
  confidence: number,
): Promise<void> {
  try {
    const { getDrizzle } = require("db");
    const drizzle = getDrizzle();
    if (drizzle) {
      const { sql } = require("drizzle-orm");
      await drizzle.execute(
        sql`INSERT INTO intent_logs (thread_id, input_text, predicted_intents, method, confidence, created_at)
            VALUES (${threadId}, ${inputText}, ${JSON.stringify(intents)}, ${method}, ${confidence}, ${new Date().toISOString()})`,
      );
      console.log(
        `[Triage Logging] Succesfully recorded intent log -> ${method} (confidence: ${confidence.toFixed(3)})`,
      );
    }
  } catch (err) {
    console.warn("[Triage Logging Exception] Bypassed log persistence:", err);
  }
}

// 快速白名单/规则 Bypass 辅助响应函数
async function handleImmediateBypass(
  state: typeof AgentStateAnnotation.State,
  routeKey: string,
  replyText: string,
  intents: IntentResult[],
  method: string,
  confidence: number,
) {
  console.log(
    `[Triage Immediate Bypass] Triggered pipeline shortcut [${routeKey}]`,
  );

  await logIntentToDB(
    state.threadId,
    state.input,
    intents.length > 0 ? intents : [{ intent: "general_query", confidence }],
    method,
    confidence,
  );

  const bypassPlan = {
    goal: "Address quick bypass query",
    subtasks: [
      {
        id: "bypass_step",
        description: `Handle immediate bypass shortcut [${routeKey}]`,
        status: "completed" as const,
        result: { message: "Bypassed successfully" },
      },
    ],
    currentStepIndex: 1,
  };

  if (state.jobId) {
    const friendlyMsg = routeKey.includes("greeting")
      ? "极速通道：已秒级识别您所发送的日常打招呼，为您载入高画质欢迎界面..."
      : routeKey.includes("out_of_scope")
        ? "业务范围提示：识别到该咨询超出了当前电商客服的处理范畴，已为您生成智能指引..."
        : "快速通道：检测到系统白名单指令，正在为您高速吐出专属答复...";

    agentEventEmitter.emit(`${state.jobId}:status`, {
      status: "executing",
      node: "triage",
      message: friendlyMsg,
      plan: bypassPlan,
    });

    setTimeout(() => {
      agentEventEmitter.emit(`${state.jobId}:result`, {
        output: replyText,
        taskPlan: bypassPlan,
      });
    }, 100);
  }

  return {
    intents,
    output: replyText,
    taskPlan: bypassPlan,
    globalTransitionsCount: -1,
    toolErrorsCount: -1,
  };
}
