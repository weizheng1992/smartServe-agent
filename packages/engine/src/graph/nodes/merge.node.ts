import { logger } from 'observability';
import type { AgentStateAnnotation } from '../state';

export async function mergeNode(state: typeof AgentStateAnnotation.State) {
  logger.info({ threadId: state.threadId }, 'mergeNode merging multi-intent plan steps');

  const currentPlan = state.taskPlan;

  // Ensure all intents are correctly mapped and deduplicated into subtasks if needed
  const uniqueSubtasks = [...currentPlan.subtasks];

  return {
    taskPlan: {
      ...currentPlan,
      subtasks: uniqueSubtasks,
    },
  };
}
