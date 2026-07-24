import { END, StateGraph } from '@langchain/langgraph';
import { logger } from 'observability';
import { EpisodicMemory, LongMemory, ShortMemory, TaskMemory } from '../memory';
import { agentEventEmitter } from './eventEmitter';
import { executorNode } from './nodes/executor.node';
import { finishNode } from './nodes/finish.node';
import { mergeNode } from './nodes/merge.node';
import { plannerNode } from './nodes/planner.node';
import { triageNode } from './nodes/triage.node';
import { validatorNode } from './nodes/validator.node';
import { AgentStateAnnotation } from './state';

export function buildAgentGraph() {
  const workflow = new StateGraph(AgentStateAnnotation)
    // Add nodes
    .addNode('triage', triageNode)
    .addNode('planner', plannerNode)
    .addNode('merge', mergeNode)
    .addNode('executor', executorNode)
    .addNode('validator', validatorNode)
    .addNode('finish', finishNode);

  // Setup workflow flow starting with triage
  workflow.addEdge('__start__', 'triage');

  // Route after triage
  workflow.addConditionalEdges(
    'triage',
    (state) => {
      // 🧠 极致提速优化（Bypass Loop Logic）：
      // 如果没有检测到任何意图，或者识别出的唯一意图是纯日常咨询/打招呼（general_query），
      // 证明本次会话不需要物理数据库或截图工具链的编排。我们直接切入 Finish 终点，彻底省去 Planner -> Executor -> Validator 重置循环！
      if (state.intents.length === 0) {
        return 'finish';
      }

      const isOnlyGeneralQuery = state.intents.length === 1 && state.intents[0].intent === 'general_query';
      if (isOnlyGeneralQuery) {
        logger.info(
          { threadId: state.threadId },
          'Detected pure general_query, bypassing planner loop to finishNode directly.',
        );
        return 'finish';
      }

      return 'planner';
    },
    {
      planner: 'planner',
      finish: 'finish',
    },
  );

  // After planner, merge/validate task structure
  workflow.addEdge('planner', 'merge');
  workflow.addEdge('merge', 'executor');
  workflow.addEdge('executor', 'validator');

  // Condition routing after validator to continue executor loop, replan, or finish
  workflow.addConditionalEdges(
    'validator',
    (state) => {
      const plan = state.taskPlan;
      const nextIndex = plan.currentStepIndex;

      // 1. 如果有任何子任务在等待审批，我们立刻提前终止 Graph 并路由到 finish 节点让其挂起！
      const hasWaitingStep = plan.subtasks.some((st) => st.result?.waitingForApproval);
      if (hasWaitingStep) {
        logger.info(
          { threadId: state.threadId },
          'Detected pending approval, routing to finish early to safely suspend.',
        );
        return 'finish';
      }

      // 2. 如果有任何子任务被管理员驳回（status === 'failed' 且 result 里面有 rejectedByAdmin: true），
      // 且我们还没有进行重规划（即当前处于刚刚拒绝的那一步），我们选择【回溯】路由到 planner 重新进行决策规划！
      const hasJustBeenRejected = plan.subtasks.some(
        (st) => st.status === 'failed' && st.result?.rejectedByAdmin && !st.result?.replanned,
      );
      if (hasJustBeenRejected) {
        logger.info(
          { threadId: state.threadId },
          'Detected administrator rejection, routing BACK to planner for cognitive re-planning!',
        );
        // 标记该拒绝步骤已被重规划受理，防止无限循环
        plan.subtasks = plan.subtasks.map((st) =>
          st.status === 'failed' && st.result?.rejectedByAdmin
            ? { ...st, result: { ...st.result, replanned: true } }
            : st,
        );
        return 'planner';
      }

      // 3. Loop circuit breaker / safety check to avoid infinite loops
      if (nextIndex >= plan.subtasks.length || nextIndex >= 10) {
        logger.info({ threadId: state.threadId }, 'Plan steps completed, routing to finish');
        return 'finish';
      }

      logger.info({ threadId: state.threadId, nextIndex }, 'Routing back to executor for next step');
      return 'executor';
    },
    {
      executor: 'executor',
      planner: 'planner',
      finish: 'finish',
    },
  );

  workflow.addEdge('finish', END);

  return workflow;
}

// 快速判定是否为基础的问候语或打招呼，实现毫秒级快速匹配，免去高昂的大模型开销！
function isQuickGreeting(msg: string): boolean {
  const clean = msg
    .trim()
    .toLowerCase()
    .replace(/[，。！？,.!?\s]/g, '');
  const greetings = [
    '你好',
    '您好',
    '哈喽',
    '哈罗',
    'hello',
    'hi',
    'hey',
    '你是谁',
    '你是哪个',
    '你是AI吗',
    '你是机器人吗',
    'who are you',
    'how are you',
  ];
  return greetings.includes(clean);
}

// Integrated invoke wrapper incorporating the 4 memories
export async function runAgent(threadId: string, userId: string, inputMessage: string, jobId?: string) {
  // Initialize memories
  const shortMemory = new ShortMemory(threadId);
  const longMemory = new LongMemory(userId);
  const taskMemory = new TaskMemory(threadId);
  const episodicMemory = new EpisodicMemory(userId);

  // 1. 🚀 毫秒级极速直达旁路：如果用户输入纯问候语/打招呼，跳过所有 LLM、向量数据库 RAG 检索！
  // 零模型开销，10毫秒瞬间完美响应！
  if (isQuickGreeting(inputMessage)) {
    const greetingText = `您好！我是您的智能电商客服助理。✨

我能为您提供以下高效率的自动化业务操作：
1. **订单物流查询**：例如 *“帮我查一下 ORD-98712 的发货状态”*
2. **快捷退款办理**：例如 *“帮我申请退款”*
3. **网页看板快照**：例如 *“帮我截取系统首页进行界面圆角核验”*

请告诉我您需要处理的业务，我将真刀真枪为您调起系统底层工具为您搞定！`;

    console.log('[Quick Greeting Bypass] Trigerred 10ms lightning bypass response!');

    // 保存对话到 PostgreSQL 会话记录表中（保障左侧历史和刷新能完美恢复）
    const userMsgId = `msg_u_${Date.now()}_${Math.random().toString(36).substr(2, 5)}`;
    const assistantMsgId = `msg_a_${Date.now()}_${Math.random().toString(36).substr(2, 5)}`;

    await shortMemory.addMessage('user', inputMessage);
    await shortMemory.addMessage('assistant', greetingText);

    try {
      const { db } = require('db');
      await db.addMessage({
        id: userMsgId,
        threadId,
        role: 'user',
        content: inputMessage,
        timestamp: new Date().toISOString(),
      });
      await db.addMessage({
        id: assistantMsgId,
        threadId,
        role: 'assistant',
        content: greetingText,
        timestamp: new Date().toISOString(),
      });
    } catch (msgErr) {
      console.warn('[DB] Failed to persist quick greeting message in physical table:', msgErr);
    }

    const mockResult = {
      output: greetingText,
      taskPlan: {
        goal: 'Bypass planner loop and respond to quick greeting directly',
        subtasks: [
          {
            id: 'respond_greeting',
            description: 'Lightning bypass welcome message',
            status: 'completed' as const,
            result: { message: 'Bypassed successfully' },
          },
        ],
        currentStepIndex: 1,
      },
    };

    if (jobId) {
      agentEventEmitter.emit(`${jobId}:status`, {
        status: 'executing',
        node: 'triage',
        message: '极速通道：已秒级识别您所发送的日常打招呼，为您载入高画质欢迎界面...',
        plan: mockResult.taskPlan,
      });
      // 延迟极微小时间给 SSE 握手
      setTimeout(() => {
        agentEventEmitter.emit(`${jobId}:result`, mockResult);
      }, 100);
    }

    return mockResult;
  }

  // 2. 🔍 性能与成本优化：如果是字数极少的非问候短文本（长度 <= 3），没有检索长期记忆和知识库 RAG 的业务必要，
  // 我们直接避开耗时的 Embedding 向量化与 RAG 检索调用（节省 1.5 秒以上首字响应延迟！）
  let longFacts: any[] = [];
  let episodicEvents: any[] = [];
  let ragDocs: any[] = [];

  if (inputMessage.trim().length > 3) {
    // SaaS 多租户隔离：根据 threadId 物理查询对应的商户 businessId
    let businessId = 'ecommerce';
    try {
      const { getDrizzle, threads } = require('db');
      const { eq } = require('drizzle-orm');
      const drizzle = getDrizzle();
      if (drizzle) {
        const threadRows = await drizzle.select().from(threads).where(eq(threads.id, threadId)).limit(1);
        if (threadRows[0]?.businessId) {
          businessId = threadRows[0].businessId;
        }
      }
    } catch (err) {
      console.warn('[RAG] Failed to select businessId for thread:', err);
    }

    const { ContextualRAG } = require('../rag/contextualRag');
    const contextualRag = new ContextualRAG(businessId);

    // 🚀 三路高度并行化 RAG 检索（长期事实记忆、情境记忆、多租户 Contextual 知识库检索）
    const [factsRes, eventsRes, ragRes] = await Promise.allSettled([
      longMemory.searchRelevantFacts(inputMessage),
      episodicMemory.retrieveEvents(inputMessage),
      contextualRag.searchRelevantDocs(inputMessage),
    ]);

    longFacts = factsRes.status === 'fulfilled' ? factsRes.value : [];
    episodicEvents = eventsRes.status === 'fulfilled' ? eventsRes.value : [];
    ragDocs = ragRes.status === 'fulfilled' ? ragRes.value : [];
  }

  // Record user query in short memory and physical Postgres messages database table
  const userMsgId = `msg_u_${Date.now()}_${Math.random().toString(36).substr(2, 5)}`;
  await shortMemory.addMessage('user', inputMessage);
  try {
    const { db } = require('db');
    await db.addMessage({
      id: userMsgId,
      threadId,
      role: 'user',
      content: inputMessage,
      timestamp: new Date().toISOString(),
    });
  } catch (msgErr) {
    console.warn('[DB] Failed to persist user message in physical table:', msgErr);
  }

  // Build and execute compiled graph
  const graphApp = buildAgentGraph().compile();

  const initialState = {
    threadId,
    userId,
    jobId: jobId || `job_local_${Date.now()}`,
    input: inputMessage,
    longMemoryFacts: longFacts,
    episodicEvents: episodicEvents,
    ragDocuments: ragDocs,
    loopCount: 0,
  };

  logger.info({ threadId, userId, jobId: initialState.jobId }, 'Invoking Agent StateGraph execution');

  if (jobId) {
    agentEventEmitter.emit(`${jobId}:status`, {
      status: 'running',
      message: 'Local LangGraph execution engine initialized',
    });
  }

  const result = await graphApp.invoke(initialState);

  // Store assistant response back into memories
  if (result.output) {
    const assistantMsgId = `msg_a_${Date.now()}_${Math.random().toString(36).substr(2, 5)}`;
    await shortMemory.addMessage('assistant', result.output);
    try {
      const { db } = require('db');
      await db.addMessage({
        id: assistantMsgId,
        threadId,
        role: 'assistant',
        content: result.output,
        timestamp: new Date().toISOString(),
      });
    } catch (msgErr) {
      console.warn('[DB] Failed to persist assistant response in physical table:', msgErr);
    }
    await episodicMemory.addEvent(
      `Handled conversation thread: ${threadId}. Output summary: ${result.output.substring(0, 80)}`,
      5,
    );
    await longMemory.extractAndStoreFact(result.output);
  }

  // Persist structured task memory if plan exists
  if (result.taskPlan) {
    await taskMemory.saveTaskState(result.taskPlan);
  }

  if (jobId) {
    agentEventEmitter.emit(`${jobId}:result`, result);
  }

  return result;
}
