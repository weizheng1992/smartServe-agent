import type { SubTask, TaskPlan } from 'types';

export function translateSubtask(st: SubTask, isResultStage = false): SubTask {
  let zhDesc = st.description;
  const descLower = st.description.toLowerCase();

  if (
    descLower.includes('order status') ||
    descLower.includes('getorderstatus') ||
    descLower.includes('shipping status') ||
    descLower.includes('order')
  ) {
    zhDesc = isResultStage
      ? '成功调起 getOrderStatus 接口，获取最新物流数据'
      : '调起 getOrderStatus 接口查询订单最新物理物流详情';
  } else if (descLower.includes('screenshot') || descLower.includes('takescreenshot')) {
    zhDesc = isResultStage
      ? '成功调起 takeScreenshot 接口，生成目标看板快照'
      : '调起 takeScreenshot 看板截图工具进行界面快照核验';
  } else if (descLower.includes('refund') || descLower.includes('processrefund')) {
    zhDesc = isResultStage
      ? '成功调起 processRefund 接口，执行快速退款并修改物理表'
      : '触发 processRefund 快速退款物理工作流';
  } else if (descLower.includes('extract')) {
    zhDesc = isResultStage ? '从用户文本中智能提取业务参数与实体 ID' : '智能捕获并定位文本中的业务关键字段与参数';
  } else if (descLower.includes('inform') || descLower.includes('communicate') || descLower.includes('tell')) {
    zhDesc = '通过大模型提炼汇总信息反馈给用户';
  }

  return {
    ...st,
    description: zhDesc,
  };
}

export function translateTaskPlan(plan: TaskPlan, isResultStage = false): TaskPlan {
  const translatedGoal =
    plan.goal.includes('Fulfill') || plan.goal.includes('Address') ? '全自动履行客户业务及工具链诉求' : plan.goal;

  return {
    ...plan,
    goal: isResultStage ? '自动化履行客户业务诉求' : translatedGoal,
    subtasks: plan.subtasks.map((st) => translateSubtask(st, isResultStage)),
  };
}
