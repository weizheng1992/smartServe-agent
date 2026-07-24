import { Annotation } from '@langchain/langgraph';

export interface TaskPlan {
  goal: string;
  subtasks: {
    id: string;
    description: string;
    status: 'pending' | 'executing' | 'completed' | 'failed';
    result?: any;
  }[];
  currentStepIndex: number;
}

export interface IntentResult {
  intent: string;
  confidence: number;
}

export const AgentStateAnnotation = Annotation.Root({
  // Unique Thread & User metadata
  threadId: Annotation<string>(),
  userId: Annotation<string>(),
  jobId: Annotation<string>({
    reducer: (x, y) => y,
    default: () => '',
  }),

  // Current inputs and history
  input: Annotation<string>(),
  history: Annotation<any[]>({
    reducer: (x, y) => x.concat(y),
    default: () => [],
  }),

  // Intent classification
  intents: Annotation<IntentResult[]>({
    reducer: (x, y) => y,
    default: () => [],
  }),

  // Task Memory
  taskPlan: Annotation<TaskPlan>({
    reducer: (x, y) => ({ ...x, ...y }),
    default: () => ({
      goal: '',
      subtasks: [],
      currentStepIndex: 0,
    }),
  }),

  // Memories loaded at start of loop
  shortMemory: Annotation<any[]>({
    reducer: (x, y) => y,
    default: () => [],
  }),
  longMemoryFacts: Annotation<any[]>({
    reducer: (x, y) => y,
    default: () => [],
  }),
  episodicEvents: Annotation<any[]>({
    reducer: (x, y) => y,
    default: () => [],
  }),
  ragDocuments: Annotation<any[]>({
    reducer: (x, y) => y,
    default: () => [],
  }),

  // Final formulation output
  output: Annotation<string>({
    reducer: (x, y) => y,
    default: () => '',
  }),

  // Loop control counters
  loopCount: Annotation<number>({
    reducer: (x, y) => y,
    default: () => 0,
  }),
});
