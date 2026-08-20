import type { IntentResult } from './agent';

export interface IntentLog {
  id?: string;
  threadId: string;
  inputText: string;
  predictedIntents: IntentResult[];
  method: 'rule' | 'embedding' | 'llm' | 'semantic_cache' | string;
  confidence: number;
  createdAt?: Date | string;
}
