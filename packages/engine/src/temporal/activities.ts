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
  state: any,
): Promise<AgentState> {
  logger.info(
    { nodeName, threadId: state.threadId },
    `Temporal activity starting for node: ${nodeName}`,
  );

  let businessId =
    state.businessConfig?.businessId || state.businessId || "ecommerce";

  if (state.threadId && (businessId === "ecommerce" || !businessId)) {
    try {
      const { getDrizzle, threads } = require("db");
      const { eq } = require("drizzle-orm");
      const drizzle = getDrizzle();
      if (drizzle) {
        const threadRows = await drizzle
          .select()
          .from(threads)
          .where(eq(threads.id, state.threadId))
          .limit(1);
        if (threadRows[0]?.businessId) {
          businessId = threadRows[0].businessId;
          state.businessId = businessId;
          if (state.businessConfig) {
            state.businessConfig.businessId = businessId;
          }
        }
      }
    } catch (err) {
      console.warn(
        "[Temporal Activities] Failed to resolve thread businessId:",
        err,
      );
    }
  }

  // Fetch memories if this is the start of execution (or prepare memories on the state object)
  if (!state.longMemoryFacts || !state.episodicEvents) {
    const longMemory = new LongMemory(state.userId, businessId);
    const episodicMemory = new EpisodicMemory(state.userId, businessId);

    const [longFacts, episodicEvents] = await Promise.all([
      longMemory.searchRelevantFacts(state.input),
      episodicMemory.retrieveEvents(state.input),
    ]);

    state.longMemoryFacts = longFacts;
    state.episodicEvents = episodicEvents;
  }

  // Ensure dynamicConfig / businessConfig is initialized
  if (!state.businessConfig || !state.businessConfig.systemPrompt) {
    let defaultLimit = 100;
    if (businessId === "nike") defaultLimit = 150;
    else if (businessId === "adidas") defaultLimit = 120;

    const { getMerchantDisplayName } = require("types");
    const brandName = getMerchantDisplayName(businessId);

    state.businessConfig = {
      businessId,
      systemPrompt: `You are an advanced, professional AI Customer Support Agent representing ${brandName}. Help users resolve order, shipping, and refund queries.`,
      intents: {
        order_status: { description: "Track or check order delivery status." },
        refund: { description: "Process or request refunds." },
        general_query: { description: "General customer questions." },
      },
      tools: [
        "getOrderStatus",
        "processRefund",
        "takeScreenshot",
        "listUserOrders",
      ],
      executionMode: "plan-and-execute",
      confidenceThresholds: { high: 0.85, mid: 0.6 },
      refundAutoApprovalLimit: defaultLimit,
      ...(state.businessConfig || {}),
    };
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

      // Commit memory updates and physically write chat records to Postgres messages table via ShortMemory!
      if (resultState.output) {
        const shortMemory = new ShortMemory(state.threadId);
        const episodicMemory = new EpisodicMemory(state.userId, businessId);
        const longMemory = new LongMemory(state.userId, businessId);

        await shortMemory.addMessage("user", state.input);
        await shortMemory.addMessage("assistant", resultState.output);

        await Promise.all([
          episodicMemory.addEvent(
            `Handled conversation thread: ${state.threadId}. Output summary: ${resultState.output.substring(0, 80)}`,
            5,
          ),
          longMemory.extractAndStoreFact(resultState.output, state.input),
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
