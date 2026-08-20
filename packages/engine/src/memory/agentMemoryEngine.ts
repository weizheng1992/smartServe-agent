import { type EpisodicEvent, EpisodicMemory } from './episodicMemory';
import { LongMemory, type LongMemoryFact } from './longMemory';
import { ShortMemory, type ShortMemoryMessage } from './shortMemory';
import { TaskMemory, type TaskState } from './taskMemory';

export interface GatheredContext {
  shortMessages: ShortMemoryMessage[];
  longFacts: LongMemoryFact[];
  taskState: TaskState | null;
  episodicEvents: EpisodicEvent[];
}

export interface RecordTurnOptions {
  userQuery?: string;
  assistantResponse?: string;
  taskState?: TaskState;
  episodicEvent?: {
    content: string;
    importance: number;
  };
}

export class AgentMemoryEngine {
  public readonly short: ShortMemory;
  public readonly long: LongMemory;
  public readonly task: TaskMemory;
  public readonly episodic: EpisodicMemory;

  public readonly threadId: string;
  public readonly userId: string;

  constructor(threadId: string, userId: string, maxTurns = 10) {
    this.threadId = threadId;
    this.userId = userId;

    this.short = new ShortMemory(threadId, maxTurns);
    this.long = new LongMemory(userId);
    this.task = new TaskMemory(threadId);
    this.episodic = new EpisodicMemory(userId);
  }

  /**
   * 🧠 原子化拉取 4 层全量记忆上下文 (Gather All 4 Memory Tiers in Parallel)
   */
  public async gatherContext(query?: string, precomputedEmbedding?: number[]): Promise<GatheredContext> {
    const [shortMessages, taskState, longFacts, episodicEvents] = await Promise.all([
      this.short.getMessages(),
      this.task.getTaskState(),
      query ? this.long.searchRelevantFacts(query, precomputedEmbedding) : Promise.resolve([]),
      query ? this.episodic.retrieveEvents(query, 3, precomputedEmbedding) : Promise.resolve([]),
    ]);

    return {
      shortMessages,
      longFacts,
      taskState,
      episodicEvents,
    };
  }

  /**
   * 📝 记录会话回合并分发更新至对应记忆层 (Record Conversational Turn Across Tiers)
   */
  public async recordTurn(options: RecordTurnOptions): Promise<void> {
    const tasks: Promise<unknown>[] = [];

    if (options.userQuery) {
      tasks.push(this.short.addMessage('user', options.userQuery));
    }

    if (options.assistantResponse) {
      tasks.push(this.short.addMessage('assistant', options.assistantResponse));
    }

    if (options.userQuery && options.assistantResponse) {
      const fullText = `Customer: ${options.userQuery}\nAssistant: ${options.assistantResponse}`;
      tasks.push(this.long.extractAndStoreFact(fullText, options.userQuery));
    }

    if (options.taskState) {
      tasks.push(this.task.saveTaskState(options.taskState));
    }

    if (options.episodicEvent) {
      tasks.push(this.episodic.addEvent(options.episodicEvent.content, options.episodicEvent.importance));
    }

    await Promise.all(tasks);
  }
}
