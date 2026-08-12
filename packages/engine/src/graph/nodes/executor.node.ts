import type { AgentStateAnnotation } from "../state";
import { StepExecutionEngine } from "./stepExecutionEngine";

export async function executorNode(state: typeof AgentStateAnnotation.State) {
  return await StepExecutionEngine.executeStep(state);
}
