import { logger } from "observability";
import { executorNode } from "../graph/nodes/executor.node";
import { finishNode } from "../graph/nodes/finish.node";
import { mergeNode } from "../graph/nodes/merge.node";
import { plannerNode } from "../graph/nodes/planner.node";
import { triageNode } from "../graph/nodes/triage.node";
import { validatorNode } from "../graph/nodes/validator.node";
import { EpisodicMemory, LongMemory, ShortMemory, TaskMemory } from "../memory";

import type { AgentState } from "../graph/state";

export async function runAgentStateNode(
  nodeName: string,
  state: AgentState,
): Promise<AgentState> {
  logger.info(
    { nodeName, threadId: state.threadId },
    `Temporal activity starting for node: ${nodeName}`,
  );

  // Fetch memories if this is the start of execution (or prepare memories on the state object)
  if (!state.longMemoryFacts || !state.episodicEvents) {
    const longMemory = new LongMemory(state.userId);
    const episodicMemory = new EpisodicMemory(state.userId);

    const [longFacts, episodicEvents] = await Promise.all([
      longMemory.searchRelevantFacts(state.input),
      episodicMemory.retrieveEvents(state.input),
    ]);

    state.longMemoryFacts = longFacts;
    state.episodicEvents = episodicEvents;
  }

  let resultState = { ...state };

  switch (nodeName) {
    case "triage": {
      const updates = await triageNode(state);
      resultState = { ...resultState, ...updates };
      break;
    }
    case "planner": {
      const updates = await plannerNode(state);
      resultState = { ...resultState, ...updates };
      break;
    }
    case "merge": {
      const updates = await mergeNode(state);
      resultState = { ...resultState, ...updates };
      break;
    }
    case "executor": {
      const updates = await executorNode(state);
      resultState = { ...resultState, ...updates };
      break;
    }
    case "validator": {
      const updates = await validatorNode(state);
      resultState = { ...resultState, ...updates };
      break;
    }
    case "finish": {
      const updates = await finishNode(state);
      resultState = { ...resultState, ...updates };

      // Commit memory updates and physically write chat records to Postgres messages table!
      if (resultState.output) {
        const shortMemory = new ShortMemory(state.threadId);
        const episodicMemory = new EpisodicMemory(state.userId);
        const longMemory = new LongMemory(state.userId);

        const userMsgId = `msg_u_${Date.now()}_${Math.random().toString(36).substr(2, 5)}`;
        const assistantMsgId = `msg_a_${Date.now()}_${Math.random().toString(36).substr(2, 5)}`;

        try {
          const { db } = require("db");
          // Physically persist user input & assistant output in PostgreSQL messages table!
          await Promise.all([
            db.addMessage({
              id: userMsgId,
              threadId: state.threadId,
              role: "user",
              content: state.input,
              timestamp: new Date().toISOString(),
            }),
            db.addMessage({
              id: assistantMsgId,
              threadId: state.threadId,
              role: "assistant",
              content: resultState.output,
              timestamp: new Date().toISOString(),
            }),
          ]);
          console.log(
            "[Temporal Activity] ✅ 对话历史已成功 100% 物理存入 PostgreSQL messages 表！",
          );
        } catch (dbErr) {
          console.error(
            "[Temporal Activity] Failed to write conversation to PostgreSQL: ",
            dbErr,
          );
        }

        await Promise.all([
          shortMemory.addMessage("user", state.input),
          shortMemory.addMessage("assistant", resultState.output),
          episodicMemory.addEvent(
            `Handled conversation thread: ${state.threadId}. Output summary: ${resultState.output.substring(0, 80)}`,
            5,
          ),
          longMemory.extractAndStoreFact(resultState.output),
        ]);
      }

      if (resultState.taskPlan) {
        const taskMemory = new TaskMemory(state.threadId);
        await taskMemory.saveTaskState(resultState.taskPlan);
      }
      break;
    }
    default:
      throw new Error(`Unknown node: ${nodeName}`);
  }

  logger.info(
    { nodeName, threadId: state.threadId },
    `Temporal activity finished for node: ${nodeName}`,
  );
  return resultState;
}
