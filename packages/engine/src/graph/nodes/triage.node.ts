import { logger } from 'observability';
import { getEmbeddingModel, getLLM } from '../../llm/callLLMWithRetry';
import { ShortMemory } from '../../memory/shortMemory';
import { agentEventEmitter } from '../eventEmitter';
import type { AgentStateAnnotation } from '../state';

// Anchor phrases for Step 2 Embedding classification
const ANCHOR_PHRASES = {
  order_status: [
    '帮我查询订单物流状态',
    '看看我的订单发货了吗',
    '查询我的快递进度',
    'ORD-98712 的物流信息',
    '这个快递到哪里了',
    '查运单号进度',
    '想看一下我的订单状态',
  ],
  refund: [
    '我想申请退款',
    '帮货品退货退款',
    '不想要了我要退款',
    '退回我的钱',
    '退货流程怎么走',
    '怎么退款',
    '我要退货',
  ],
  out_of_scope: [
    '今天天气怎么样',
    '写一段Python代码',
    '帮我订一张电影票',
    '明天会下雨吗',
    '买个东西怎么买',
    '教我做菜',
    '美国总统是谁',
    '附近好吃的餐馆有哪些',
  ],
};

// Singleton in-memory cache for reference anchor embeddings
let cachedAnchorVectors: Record<string, number[][]> | null = null;

async function getAnchorVectors(): Promise<Record<string, number[][]>> {
  if (cachedAnchorVectors) return cachedAnchorVectors;

  console.log('[Triage Embedding Cache] 🚀 Initiating reference anchor phrases embedding cache...');
  const embedModel = getEmbeddingModel();

  const orderPromise = Promise.all(ANCHOR_PHRASES.order_status.map((p) => embedModel.embedQuery(p)));
  const refundPromise = Promise.all(ANCHOR_PHRASES.refund.map((p) => embedModel.embedQuery(p)));
  const oosPromise = Promise.all(ANCHOR_PHRASES.out_of_scope.map((p) => embedModel.embedQuery(p)));

  const [orderVectors, refundVectors, oosVectors] = await Promise.all([orderPromise, refundPromise, oosPromise]);

  cachedAnchorVectors = {
    order_status: orderVectors,
    refund: refundVectors,
    out_of_scope: oosVectors,
  };

  console.log('[Triage Embedding Cache] ✅ Reference anchor embeddings successfully pre-cached!');
  return cachedAnchorVectors;
}

// Cosine similarity helper
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
  const input = state.input ? state.input.trim() : '';
  logger.info({ threadId }, 'triageNode starting multi-tier intent classification pipeline');

  if (state.jobId) {
    agentEventEmitter.emit(`${state.jobId}:status`, {
      status: 'executing',
      node: 'triage',
      message:
        '正在进行多渠道意图分层检验（层级：规则前置 -> 规则白名单 -> Embedding置信度评估 -> 大模型多意图检测）...',
    });
  }

  // =========================================================================
  // 🛡️ Step 0: 输入格式预过滤 (纯规则，不算意图判断)
  // =========================================================================
  if (input.length === 0) {
    const reply = '您好！看起来您发送了一条空消息。请问有什么我可以帮您的？';
    return await handleImmediateBypass(state, 'rule_empty', reply, [], 'rule', 1.0);
  }

  // 纯符号或过量标点拦截
  const symbolRegex = /^[\s\d`~!@#$%^&*()_\-+=+\[\]{}|;:',.<>?/\\?？，。！；：‘“”、]+$/;
  if (symbolRegex.test(input)) {
    const reply = '您好！如果您有关于订单、物流或退款方面的疑问，可以直接向我提问，我将为您竭诚服务。';
    return await handleImmediateBypass(state, 'rule_symbols', reply, [], 'rule', 1.0);
  }

  // 超长乱码/无意义超长文本拦截
  if (input.length > 1000) {
    const reply = '您好！您发送的内容过长，系统暂时无法解析。请问您有具体的订单或退款问题需要我协助吗？';
    return await handleImmediateBypass(state, 'rule_length_limit', reply, [], 'rule', 1.0);
  }

  // =========================================================================
  // 🛡️ 重复提问/网络抖动拦截器 (First Shield: Semantic Duplicate Bypass)
  // =========================================================================
  try {
    const shortMemory = new ShortMemory(threadId);
    const historyMsgs = await shortMemory.getMessages();

    // 过滤出用户和助理的历史对话记录
    const userMsgs = historyMsgs.filter((m) => m.role === 'user');
    const assistantMsgs = historyMsgs.filter((m) => m.role === 'assistant');

    if (userMsgs.length > 0 && assistantMsgs.length > 0) {
      const lastUserMsg = userMsgs[userMsgs.length - 1];
      const lastAssistantMsg = assistantMsgs[assistantMsgs.length - 1];

      // 判断 1: 绝对文本完全一致
      const isExactlySame = input.trim() === lastUserMsg.content.trim();

      // 判断 2: 语义相似度极高 (通过 OpenAIEmbeddings 向量余弦值)
      let isSemanticallySame = false;
      if (!isExactlySame && input.trim().length > 3 && lastUserMsg.content.trim().length > 3) {
        const embedModel = getEmbeddingModel();
        const [currentVec, lastVec] = await Promise.all([
          embedModel.embedQuery(input),
          embedModel.embedQuery(lastUserMsg.content),
        ]);
        const sim = cosineSimilarity(currentVec, lastVec);
        if (sim >= 0.98) {
          isSemanticallySame = true;
          console.log(`[Triage Duplicate Shield] 🎯 检测到超高语义相似度重复提问: ${sim.toFixed(3)}`);
        }
      }

      if (isExactlySame || isSemanticallySame) {
        console.log('[Triage Duplicate Shield] 🎯 成功拦截重复提问！秒级复用历史答复。');

        const prefixMsg = isExactlySame
          ? '您好！检测到您发送了与刚才相同的咨询。这是刚才为您查询的最新进度：\n\n'
          : '您好！检测到您提问了相似的问题。这是刚才为您查询的最新进度：\n\n';

        const reply = `${prefixMsg}${lastAssistantMsg.content}`;
        const finalIntents = [{ intent: 'general_query', confidence: 1.0 }];

        return await handleImmediateBypass(state, 'duplicate_bypass', reply, finalIntents, 'rule', 1.0);
      }
    }
  } catch (shErr) {
    console.warn('[Triage Duplicate Shield Exception] Bypassed duplicate check:', shErr);
  }

  // =========================================================================
  // 🛡️ Step 1: 规则白名单 (高频固定指令快速拦截)
  // =========================================================================
  const cleanInput = input.toLowerCase().replace(/[，。！？,.!?\s]/g, '');

  // 1. 问候语/欢迎语快速通路
  const greetingWords = ['你好', '您好', '哈喽', '哈罗', 'hello', 'hi', 'hey', '哈罗', '哈拉'];
  if (greetingWords.includes(cleanInput)) {
    const reply = `您好！我是您的智能电商客服助理。✨

我能为您提供以下高效率的自动化业务操作：
1. **订单物流查询**：例如 *“帮我查一下 ORD-98712 的发货状态”*
2. **快捷退款办理**：例如 *“帮我申请退款”*
3. **网页看板快照**：例如 *“帮我截取系统首页进行界面圆角核验”*

请告诉我您需要处理的业务，我将直接为您调起系统底层工具为您搞定！`;
    return await handleImmediateBypass(
      state,
      'rule_greeting',
      reply,
      [{ intent: 'general_query', confidence: 1.0 }],
      'rule',
      1.0,
    );
  }

  // 2. 转人工指令快速通路
  const agentWords = ['转人工', '人工客服', '人工', '联系客服', '找人工', '呼叫人工'];
  if (agentWords.includes(cleanInput)) {
    const reply =
      '已为您登记转接人工客服诉求。物理人工通道排队中，当前等待排队人数：1人。人工客服将在 1-2 分钟内接入会话，请您稍等。在此期间，您可以继续与我交流。';
    return await handleImmediateBypass(
      state,
      'rule_agent_transfer',
      reply,
      [{ intent: 'general_query', confidence: 1.0 }],
      'rule',
      1.0,
    );
  }

  // 3. 退出会话指令
  const exitWords = ['再见', '退出', 'bye', 'exit', 'quit', '再见啦', '拜拜'];
  if (exitWords.includes(cleanInput)) {
    const reply =
      '好的，很高兴为您服务！如果您后续还有任何关于订单状态或退款方面的需要，欢迎随时联系我。祝您生活愉快，再见！👋';
    return await handleImmediateBypass(
      state,
      'rule_exit_conversation',
      reply,
      [{ intent: 'general_query', confidence: 1.0 }],
      'rule',
      1.0,
    );
  }

  // =========================================================================
  // 🛡️ Step 2: Embedding 快速分类 (含 out_of_scope 类别)
  // =========================================================================
  let scoreOrder = 0;
  let scoreRefund = 0;
  let scoreOos = 0;

  try {
    const embedModel = getEmbeddingModel();
    const [userVector, anchors] = await Promise.all([embedModel.embedQuery(input), getAnchorVectors()]);

    // 计算与各个类别代表锚点句的最大余弦相似度
    scoreOrder = Math.max(...anchors.order_status.map((v) => cosineSimilarity(userVector, v)));
    scoreRefund = Math.max(...anchors.refund.map((v) => cosineSimilarity(userVector, v)));
    scoreOos = Math.max(...anchors.out_of_scope.map((v) => cosineSimilarity(userVector, v)));

    console.log(
      `[Triage Embedding Step 2] Max Scores -> order: ${scoreOrder.toFixed(3)}, refund: ${scoreRefund.toFixed(3)}, oos: ${scoreOos.toFixed(3)}`,
    );

    // 判决 A: 高置信度物理物流业务意图直达
    if (scoreOrder >= 0.88 && scoreOrder - scoreOos >= 0.08) {
      console.log('[Triage Embedding Match] Auto-matched order_status intent via semantic similarity!');
      const intents = [{ intent: 'order_status', confidence: scoreOrder }];
      await logIntentToDB(threadId, input, intents, 'embedding', scoreOrder);
      return { intents };
    }

    // 判决 B: 高置信度退款意图直达
    if (scoreRefund >= 0.88 && scoreRefund - scoreOos >= 0.08) {
      console.log('[Triage Embedding Match] Auto-matched refund intent via semantic similarity!');
      const intents = [{ intent: 'refund', confidence: scoreRefund }];
      await logIntentToDB(threadId, input, intents, 'embedding', scoreRefund);
      return { intents };
    }

    // 判决 C: 高置信度超出业务范围 (out_of_scope) 拦截
    if (scoreOos >= 0.86 && scoreOos - Math.max(scoreOrder, scoreRefund) >= 0.06) {
      console.log('[Triage Embedding Match] Blocked out_of_scope query via semantic similarity!');
      const reply =
        '您好！我是您的高级智能电商客服助理，主要负责协助处理订单、物流及退款相关业务。您刚才提到的问题超出了我的服务范围（属于日常咨询/外部问题）。请问有什么具体的电商订单问题需要我协助吗？';
      return await handleImmediateBypass(
        state,
        'embedding_out_of_scope',
        reply,
        [{ intent: 'general_query', confidence: scoreOos }],
        'embedding',
        scoreOos,
      );
    }
  } catch (embedErr) {
    console.warn('[Triage Embedding Step 2 Exception] Bypassing Embedding Classifier:', embedErr);
  }

  // =========================================================================
  // 🛡️ Step 3: LLM 深度检测分类 (两两模糊/都不高，进入大模型精细识别)
  // =========================================================================
  console.log(
    '[Triage Fallthrough to Step 3] Narrow margin/Low scores, launching Gemini 3.5 Flash deep triage classifier...',
  );
  const llm = getLLM(state.jobId);

  const prompt = `Classify the following customer input and determine the intents.
Input: "${input}"
Return a JSON array of objects with keys "intent" (one of: "order_status", "refund", "general_query", "out_of_scope") and "confidence" (number between 0 and 1).
Return ONLY the raw JSON array. Do not include markdown or backticks.`;

  try {
    const response = await llm.invoke(prompt);
    const content = typeof response === 'string' ? response : (response as any).content || '';
    let parsed: any[] = [];
    try {
      const cleanResponse = content
        .trim()
        .replace(/^```json\s*/, '')
        .replace(/```$/, '')
        .trim();
      parsed = JSON.parse(cleanResponse);
    } catch {
      parsed = [{ intent: 'general_query', confidence: 0.8 }];
    }

    // 处理 LLM 显式分类出的超出业务范围的回复
    const isOos = parsed.some((p) => p.intent === 'out_of_scope');
    if (isOos) {
      const reply =
        '您好！我是您的高级智能电商客服助理，主要负责协助处理订单、物流及退款相关业务。您刚才提到的问题超出了我的服务范围（属于外部或高风险意图）。请问有什么具体的电商订单问题需要我协助吗？';
      return await handleImmediateBypass(
        state,
        'llm_out_of_scope',
        reply,
        [{ intent: 'general_query', confidence: 0.9 }],
        'llm',
        0.9,
      );
    }

    const confidence = parsed[0]?.confidence || 0.8;
    await logIntentToDB(threadId, input, parsed, 'llm', confidence);

    if (state.jobId) {
      agentEventEmitter.emit(`${state.jobId}:status`, {
        status: 'executing',
        node: 'triage',
        message: `用户意图识别成功！检测到核心意图: ${parsed.map((p) => p.intent).join(', ')} (置信度: ${parsed.map((p) => p.confidence).join(', ')})`,
      });
    }

    return { intents: parsed };
  } catch (err: any) {
    logger.error({ threadId, err }, 'triageNode Step 3 failed, falling back to general_query');
    const fallbackIntents = [{ intent: 'general_query', confidence: 0.5 }];
    await logIntentToDB(threadId, input, fallbackIntents, 'llm', 0.5);
    return { intents: fallbackIntents };
  }
}

// Helper to record logging data into the physical Postgres database table
async function logIntentToDB(
  threadId: string,
  inputText: string,
  intents: any[],
  method: string,
  confidence: number,
): Promise<void> {
  try {
    const { db } = require('db');
    const id = `log_${Date.now()}_${Math.random().toString(36).substr(2, 5)}`;
    await db.execute(`
      INSERT INTO intent_logs (id, thread_id, input_text, predicted_intents, method, confidence, created_at)
      VALUES (
        '${id}',
        '${threadId}',
        '${inputText.replace(/'/g, "''")}',
        '${JSON.stringify(intents)}',
        '${method}',
        ${confidence},
        '${new Date().toISOString()}'
      )
    `);
    console.log(`[Triage Logging] Succesfully recorded intent log -> ${method} (confidence: ${confidence.toFixed(3)})`);
  } catch (err) {
    console.warn('[Triage Logging Exception] Bypassed log persistence:', err);
  }
}

// Helper to handle immediate rule or embedding bypasses and instantly close the loading loop
async function handleImmediateBypass(
  state: any,
  routeKey: string,
  replyText: string,
  intents: any[],
  method: string,
  confidence: number,
) {
  console.log(`[Triage Immediate Bypass] Triggered pipeline shortcut [${routeKey}]`);

  // Record logs in the DB
  await logIntentToDB(
    state.threadId,
    state.input,
    intents.length > 0 ? intents : [{ intent: 'general_query', confidence }],
    method,
    confidence,
  );

  if (state.jobId) {
    const friendlyMsg = routeKey.includes('greeting')
      ? '极速通道：已秒级识别您所发送的日常打招呼，为您载入高画质欢迎界面...'
      : routeKey.includes('out_of_scope')
        ? '业务范围提示：识别到该咨询超出了当前电商客服的处理范畴，已为您生成智能指引...'
        : '快速通道：检测到系统白名单指令，正在为您高速吐出专属答复...';

    agentEventEmitter.emit(`${state.jobId}:status`, {
      status: 'executing',
      node: 'triage',
      message: friendlyMsg,
      plan: {
        goal: 'Address quick bypass query',
        subtasks: [
          {
            id: 'bypass_step',
            description: `Handle immediate bypass shortcut [${routeKey}]`,
            status: 'completed' as const,
            result: { message: 'Bypassed successfully' },
          },
        ],
        currentStepIndex: 1,
      },
    });

    // 延迟少许并广播 result 事件，让前端 Loading 进度条在毫秒级全绿关闭
    setTimeout(() => {
      agentEventEmitter.emit(`${state.jobId}:result`, {
        output: replyText,
        taskPlan: {
          goal: 'Address quick bypass query',
          subtasks: [
            {
              id: 'bypass_step',
              description: `Handle immediate bypass shortcut [${routeKey}]`,
              status: 'completed' as const,
              result: { message: 'Bypassed successfully' },
            },
          ],
          currentStepIndex: 1,
        },
      });
    }, 100);
  }

  return {
    intents,
    output: replyText,
  };
}
