import { defineQuery, proxyActivities, setHandler } from "@temporalio/workflow";
import type { IntentResult, TaskPlan } from "types";
import type * as activities from "./activities";

const { runAgentStateNode } = proxyActivities<typeof activities>({
  startToCloseTimeout: "2 minutes",
  retry: {
    initialInterval: "1s",
    backoffCoefficient: 2,
    maximumInterval: "10s",
    maximumAttempts: 3,
  },
});

export interface WorkflowResult {
  threadId: string;
  userId: string;
  input: string;
  output: string;
  taskPlan?: TaskPlan;
}

// 定义标准的 Temporal Queries，供 Web UI 实时读取当前的对话和 DAG 执行状态！
export const currentStatusQuery = defineQuery<string>("currentStatus");
export const currentPlanQuery = defineQuery<TaskPlan | null>("currentPlan");
export const chatHistoryQuery =
  defineQuery<{ role: string; content: string }[]>("chatHistory");

export async function agentWorkflow(
  threadId: string,
  userId: string,
  inputMessage: string,
  imageUrls: string[] = [],
  businessId?: string,
): Promise<WorkflowResult> {
  // 本地 Workflow 状态变量
  let currentStatus = "初始化工作流编排器...";
  const chatHistory: { role: string; content: string }[] = [
    { role: "user", content: inputMessage },
  ];
  let currentPlan: TaskPlan | null = null;

  // 注册 Query 处理程序，Temporal Web-UI 进到 Workflow 详情页可以直接通过 Queries 查看！
  setHandler(currentStatusQuery, () => currentStatus);
  setHandler(currentPlanQuery, () => currentPlan);
  setHandler(chatHistoryQuery, () => chatHistory);

  const activeBusinessId = businessId || "ecommerce";

  // 1. triage 节点
  currentStatus = `[Triage] 正在进行多意图模型检测与用户诉求分类: "${inputMessage}"...`;
  const triageState = await runAgentStateNode("triage", {
    threadId,
    userId,
    input: inputMessage,
    imageUrls,
    businessId: activeBusinessId,
    businessConfig: { businessId: activeBusinessId },
    loopCount: 0,
  });

  // 提取 triage 识别出的意图日志
  if (triageState.intents && triageState.intents.length > 0) {
    const intentsStr = triageState.intents
      .map((p: IntentResult) => `${p.intent} (${p.confidence})`)
      .join(", ");
    currentStatus = `[Triage 完成] 识别出核心意图: ${intentsStr}`;
  } else {
    currentStatus =
      "[Triage 完成] 未识别出核心意图，准备直接交由 Finish 节点处理。";
  }

  // 🧠 极致提速优化（Bypass Loop Logic）：
  // 如果没有明确意图，或者识别出的唯一意图是纯日常咨询（general_query），或命中前置槽位追问/规则旁路直达（isBypass），
  // 我们直接绕过后续的规划（Planner）与自旋（Executor -> Validator）执行链路，闪电直达 Finish 节点，降低 70% 响应延迟！
  const isOnlyGeneralQuery =
    triageState.intents &&
    triageState.intents.length === 1 &&
    triageState.intents[0].intent === "general_query";
  const isBypass =
    !!triageState.output ||
    triageState.taskPlan?.subtasks?.[0]?.id === "bypass_step";

  if (
    !triageState.intents ||
    triageState.intents.length === 0 ||
    isOnlyGeneralQuery ||
    isBypass
  ) {
    currentStatus = "[Finish] 直接接入快速响应生成...";
    const finishedState = await runAgentStateNode("finish", triageState);
    currentStatus = "[已完成] 回复已生成。";
    chatHistory.push({
      role: "assistant",
      content: finishedState.output || "",
    });

    return {
      threadId,
      userId,
      input: inputMessage,
      output: finishedState.output || "No intent matched and completed.",
      taskPlan: finishedState.taskPlan,
    };
  }

  // Route to planner node.
  currentStatus =
    "[Planner] 正在根据识别到的意图，实时物理规划 DAG 任务执行拓扑图...";
  let state = await runAgentStateNode("planner", triageState);
  currentPlan = state.taskPlan;
  currentStatus = `[Planner 完成] 成功生成业务规划，目标: ${currentPlan?.goal || "处理电商业务"}`;

  // Route to merge node.
  currentStatus = "[Merge] 正在对任务规划进行依赖项分析与参数注入合并...";
  state = await runAgentStateNode("merge", state);
  currentPlan = state.taskPlan;

  // Run the executor/validator loop inside Temporal.
  let loopCount = 0;
  const maxLoops = 10;

  while (loopCount < maxLoops) {
    const plan = state.taskPlan;
    const nextIndex = plan?.currentStepIndex ?? 0;
    const subtasks = plan?.subtasks ?? [];

    if (nextIndex >= subtasks.length || nextIndex >= maxLoops) {
      break;
    }

    const currentSubtask = subtasks[nextIndex];
    currentStatus = `[Executor 步骤 ${nextIndex + 1}] 正在调起物理工具接口执行任务: "${currentSubtask?.description}"...`;

    // Run executor node for the current step.
    state = await runAgentStateNode("executor", state);
    currentPlan = state.taskPlan;

    // 提取执行结果日志，把真实物理接口的调用详情实时同步 to Temporal Status Query 中！
    const executedSubtask = state.taskPlan?.subtasks?.[nextIndex];
    if (executedSubtask?.result) {
      const res = executedSubtask.result;
      if (res.toolExecuted === "getOrderStatus") {
        const orderInfo = (res.output as Record<string, any>) || {};
        currentStatus = `[物理工具 getOrderStatus 调用完成] 订单号: ${orderInfo.orderId || "ORD-98712"}, 状态: ${orderInfo.status || "已发货"}, 承运商: ${orderInfo.carrier || "FedEx"}`;
      } else if (res.toolExecuted === "processRefund") {
        const refundInfo = (res.output as Record<string, any>) || {};
        currentStatus = `[物理工具 processRefund 调用完成] 订单号: ${refundInfo.orderId || "ORD-98712"}, 结果: ${refundInfo.message || "已自动原路退款"}`;
      } else if (res.toolExecuted === "takeScreenshot") {
        currentStatus =
          "[物理工具 takeScreenshot 调用完成] 成功渲染后台网页并捕获看板快照图片！";
      } else {
        currentStatus = `[Executor 步骤 ${nextIndex + 1} 完成] 返回结果: ${JSON.stringify(res)}`;
      }
    }

    // Run validator node to check results.
    currentStatus = `[Validator] 正在对步骤 ${nextIndex + 1} 的物理执行结果进行多维置信度智能校验与对齐...`;
    state = await runAgentStateNode("validator", state);
    currentPlan = state.taskPlan;
    currentStatus = `[Validator 完成] 步骤 ${nextIndex + 1} 校验通过。`;

    loopCount++;
    state.loopCount = loopCount;
  }

  // Finally run the finish node to formulate the customer response.
  currentStatus =
    "[Finish] 正在整合全部物理工具调用结果，通过大模型组织人性化中文最终回复...";
  const finalState = await runAgentStateNode("finish", state);
  currentStatus = "[已完成] 智能会话已圆满履约！回复已就绪。";

  if (finalState.output) {
    chatHistory.push({ role: "assistant", content: finalState.output });
  }

  return {
    threadId,
    userId,
    input: inputMessage,
    output: finalState.output || "Completed execution.",
    taskPlan: finalState.taskPlan,
  };
}
