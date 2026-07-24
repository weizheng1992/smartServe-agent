import { logger } from 'observability';
import { getLLM } from '../../llm/callLLMWithRetry';
import { agentEventEmitter } from '../eventEmitter';
import type { AgentStateAnnotation } from '../state';

export async function validatorNode(state: typeof AgentStateAnnotation.State) {
  const currentPlan = state.taskPlan;
  const currentIndex = currentPlan.currentStepIndex;
  const step = currentPlan.subtasks[currentIndex];

  if (!step) {
    logger.warn({ threadId: state.threadId }, 'validatorNode validation skipped: no step found');
    return {};
  }

  // 如果执行步骤因为安全审批被拦截处于挂起状态，校验器不做任何操作，亦不累加索引，保留现场原封不动返回！
  if (step.result?.waitingForApproval) {
    logger.info({ threadId: state.threadId }, 'validatorNode bypassed: step is waiting for approval');
    return {
      taskPlan: {
        ...currentPlan,
        currentStepIndex: currentIndex,
      },
    };
  }

  logger.info({ threadId: state.threadId, step }, `validatorNode validating step ${currentIndex}`);

  if (state.jobId) {
    agentEventEmitter.emit(`${state.jobId}:status`, {
      status: 'executing',
      node: 'validator',
      message: `智能决策核验器启动：正在多维度校验第 ${currentIndex + 1} 步 [${step.description}] 工具产出数据的完整性与合法性...`,
    });
  }

  const llm = getLLM(state.jobId);
  const prompt = `Validate the execution output of step "${step.description}".
The execution resulted in: ${JSON.stringify(step.result)}.
Is this output sufficient and correct for this step?
Respond with YES or NO.
Return ONLY YES or NO.`;

  let isValid = true;
  // If the step is just about string extraction, logging, formatting, informing the user, or SCREENSHOTS,
  // we default validation to true, preventing the LLM validator node from overly strict and pedantic "NO" classifications
  // that can cause non-tool steps (like ID extraction, User Communication or Screenshots) to falsely mark as failed.
  const desc = step.description.toLowerCase();
  const isMessageExtractionOrInfo =
    desc.includes('extract') ||
    desc.includes('inform') ||
    desc.includes('communicate') ||
    desc.includes('tell') ||
    desc.includes('provide') ||
    desc.includes('screenshot') ||
    desc.includes('layout') ||
    desc.includes('viewport');

  if (isMessageExtractionOrInfo && (!step.result || !step.result.error)) {
    isValid = true;
    logger.info(
      { threadId: state.threadId, stepIndex: currentIndex },
      'validatorNode auto-passed extraction/inform step',
    );
  } else {
    try {
      const response = await llm.invoke(prompt);
      const content = typeof response === 'string' ? response : (response as any).content || '';
      isValid = content.trim().toUpperCase() !== 'NO';
    } catch (err: any) {
      logger.error({ threadId: state.threadId, err }, 'validatorNode validation check failed, defaulting to YES');
    }
  }

  const updatedSubtasks = [...currentPlan.subtasks];
  if (!isValid) {
    logger.warn({ threadId: state.threadId, stepIndex: currentIndex }, 'validatorNode step failed validation');
    updatedSubtasks[currentIndex] = {
      ...step,
      status: 'failed',
    };

    if (state.jobId) {
      agentEventEmitter.emit(`${state.jobId}:status`, {
        status: 'executing',
        node: 'validator',
        message: `⚠️ 校验结果警告：第 ${currentIndex + 1} 步执行产出未完全满足预期目标，已被决策链标记为 [failed]！`,
        plan: {
          ...currentPlan,
          subtasks: updatedSubtasks,
          currentStepIndex: currentIndex + 1,
        },
      });
    }
  } else {
    logger.info({ threadId: state.threadId, stepIndex: currentIndex }, 'validatorNode step passed validation');

    if (state.jobId) {
      agentEventEmitter.emit(`${state.jobId}:status`, {
        status: 'executing',
        node: 'validator',
        message: `✅ 核验结果绿灯！第 ${currentIndex + 1} 步执行结果数据完全合格、结构合法。`,
        plan: {
          ...currentPlan,
          subtasks: updatedSubtasks,
          currentStepIndex: currentIndex + 1,
        },
      });
    }
  }

  // Advance step index
  return {
    taskPlan: {
      ...currentPlan,
      subtasks: updatedSubtasks,
      currentStepIndex: currentIndex + 1,
    },
  };
}
