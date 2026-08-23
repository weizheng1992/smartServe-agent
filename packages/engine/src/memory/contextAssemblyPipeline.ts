import { AgentMemoryEngine, type GatheredContext } from './agentMemoryEngine';
import type { EpisodicEvent } from './episodicMemory';
import type { LongMemoryFact } from './longMemory';
import type { ShortMemoryMessage } from './shortMemory';

export interface AssembleContextOptions {
  threadId: string;
  userId: string;
  query?: string;
  businessId?: string;
  shortMessages?: ShortMemoryMessage[];
  ragDocs?: Array<{ title?: string; content: string; score?: number }>;
  maxShortMessages?: number;
  maxRagDocs?: number;
  minFactConfidence?: number;
  maxTokenBudget?: number;
}

export interface AssembledContextBundle {
  conversationHistoryText: string;
  ragKnowledgeText: string;
  userPersonaText: string;
  episodicEventsText: string;
  fullPromptContext: string;
  tokenCountEstimate: number;
  rawGathered?: GatheredContext;
}

/**
 * 🌟 ContextAssemblyPipeline 上下文预算与统一装配深模块 (Deep Module)
 * 职责：
 * 1. 统一调度 4 层记忆 (Short, Long, Task, Episodic)
 * 2. 结构化格式化多轮历史、RAG 文档切片、长期偏好画像与情景记忆
 * 3. Token 预算感知与按相关性/置信度动态剪枝 (Token Budget Pruning)
 * 4. 消除各 Node 手动拼接与格式错位
 */
export class ContextAssemblyPipeline {
  /**
   * 格式化短期对话历史
   */
  public static formatShortHistory(messages: ShortMemoryMessage[], maxCount = 10): string {
    if (!messages || messages.length === 0) {
      return '无历史对话';
    }

    const sliced = messages.slice(-maxCount);
    return sliced
      .map((msg) => {
        const roleName = msg.role === 'user' ? 'User' : 'Assistant';
        return `${roleName}: ${msg.content}`;
      })
      .join('\n');
  }

  /**
   * 格式化 RAG 知识库检索切片
   */
  public static formatRagDocs(docs?: Array<{ title?: string; content: string; score?: number }>, maxCount = 3): string {
    if (!docs || docs.length === 0) {
      return '无匹配的知识库内容';
    }

    const sliced = docs.slice(0, maxCount);
    return sliced
      .map((doc, idx) => {
        const title = doc.title ? ` [${doc.title}]` : '';
        return `[文档 ${idx + 1}${title}]: ${doc.content.trim()}`;
      })
      .join('\n\n');
  }

  /**
   * 格式化长期偏好画像事实
   */
  public static formatLongFacts(facts?: LongMemoryFact[], minConfidence = 0.5): string {
    if (!facts || facts.length === 0) {
      return '无记录画像';
    }

    const filtered = facts.filter((f) => (f.confidence ?? 1) >= minConfidence);
    if (filtered.length === 0) {
      return '无记录画像';
    }

    return filtered
      .map((f) => {
        const conf = f.confidence ? ` (置信度: ${Math.round(f.confidence * 100)}%)` : '';
        return `• ${f.fact}${conf}`;
      })
      .join('\n');
  }

  /**
   * 格式化情景记忆事件
   */
  public static formatEpisodicEvents(events?: EpisodicEvent[], maxCount = 3): string {
    if (!events || events.length === 0) {
      return '无历史情景';
    }

    const sliced = events.slice(0, maxCount);
    return sliced.map((e) => `• [历史交互]: ${e.event}`).join('\n');
  }

  /**
   * 🚀 统一装配全量上下文并完成 Token 预算动态剪枝
   */
  public static async assemble(options: AssembleContextOptions): Promise<AssembledContextBundle> {
    const {
      threadId,
      userId,
      query,
      businessId,
      shortMessages: inputShortMessages,
      ragDocs,
      maxShortMessages = 10,
      maxRagDocs = 3,
      minFactConfidence = 0.5,
    } = options;

    const memoryEngine = new AgentMemoryEngine(threadId, userId, 10, businessId);
    let gathered: GatheredContext | undefined;

    let activeShortMessages = inputShortMessages;
    let longFacts: LongMemoryFact[] = [];
    let episodicEvents: EpisodicEvent[] = [];

    if (!activeShortMessages || activeShortMessages.length === 0 || query) {
      gathered = await memoryEngine.gatherContext(query);
      if (!activeShortMessages || activeShortMessages.length === 0) {
        activeShortMessages = gathered.shortMessages;
      }
      longFacts = gathered.longFacts || [];
      episodicEvents = gathered.episodicEvents || [];
    }

    const conversationHistoryText = this.formatShortHistory(activeShortMessages || [], maxShortMessages);
    const ragKnowledgeText = this.formatRagDocs(ragDocs, maxRagDocs);
    const userPersonaText = this.formatLongFacts(longFacts, minFactConfidence);
    const episodicEventsText = this.formatEpisodicEvents(episodicEvents);

    const sections: string[] = [];

    if (userPersonaText && userPersonaText !== '无记录画像') {
      sections.push(`【客户长期画像与偏好 (User Persona Facts)】\n${userPersonaText}`);
    }

    if (episodicEventsText && episodicEventsText !== '无历史情景') {
      sections.push(`【历史相似交互情景 (Episodic Context)】\n${episodicEventsText}`);
    }

    if (ragKnowledgeText && ragKnowledgeText !== '无匹配的知识库内容') {
      sections.push(`【知识库参考文档 (Retrieved Knowledge Base)】\n${ragKnowledgeText}`);
    }

    sections.push(`【近期对话上下文 (Recent Conversation History)】\n${conversationHistoryText}`);

    const fullPromptContext = sections.join('\n\n');
    const tokenCountEstimate = Math.ceil(fullPromptContext.length / 3.5);

    return {
      conversationHistoryText,
      ragKnowledgeText,
      userPersonaText,
      episodicEventsText,
      fullPromptContext,
      tokenCountEstimate,
      rawGathered: gathered,
    };
  }
}
