import type { AgentStateAnnotation } from "../state";
import { IntentTriageEngine } from "./triage/intentTriageEngine";
import {
  DEFAULT_ANCHOR_PHRASES,
  SemanticVectorCache,
  type SupportedIntent,
} from "./triage/semanticCache";

export { IntentTriageEngine, DEFAULT_ANCHOR_PHRASES, type SupportedIntent };

export function addQueryToSemanticCache(
  businessId: string,
  query: string,
  reply: string,
  vector: number[],
): void {
  SemanticVectorCache.addQueryToSemanticCache(businessId, query, reply, vector);
}

export async function triageNode(state: typeof AgentStateAnnotation.State) {
  return IntentTriageEngine.process(state);
}
