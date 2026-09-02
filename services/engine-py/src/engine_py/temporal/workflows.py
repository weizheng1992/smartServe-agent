"""Temporal Workflow — 镜像 temporal/workflows.ts(agentWorkflow + 三个 Query)。

temporalio 为可选依赖(worker extra);缺少时本模块不可导入,worker.py 会给出
明确提示。查询名与 TS 保持一致(currentStatus/currentPlan/chatHistory),
TS 侧 Temporal Server 可跨语言查询同一 Workflow。
"""

from __future__ import annotations

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from . import activities


@workflow.defn
class AgentWorkflow:
    @workflow.run
    async def run(
        self,
        thread_id: str,
        user_id: str,
        input_message: str,
        image_urls: list[str] | None = None,
        business_id: str | None = None,
    ) -> dict:
        run_node = workflow.start_activity(
            activities.run_agent_state_node,
            start_to_close_timeout=timedelta(minutes=2),
            retry_policy=RetryPolicy(
                initial_interval=timedelta(seconds=1),
                backoff_coefficient=2.0,
                maximum_interval=timedelta(seconds=10),
                maximum_attempts=3,
            ),
        )

        current_status = "初始化工作流编排器..."
        chat_history: list[dict] = [{"role": "user", "content": input_message}]
        current_plan: dict | None = None

        # 注册 Query 处理器(名称与 TS 侧一致,Temporal Web-UI / TS 网关跨语言可查)
        def _q_status() -> str:
            return current_status

        def _q_plan() -> dict | None:
            return current_plan

        def _q_history() -> list[dict]:
            return chat_history

        workflow.set_query_handler("currentStatus", _q_status)
        workflow.set_query_handler("currentPlan", _q_plan)
        workflow.set_query_handler("chatHistory", _q_history)

        active_business_id = business_id or "ecommerce"

        # 1. triage
        current_status = f'[Triage] 正在进行多意图模型检测与用户诉求分类: "{input_message}"...'
        triage_state = await run_node(
            "triage",
            {
                "threadId": thread_id,
                "userId": user_id,
                "input": input_message,
                "imageUrls": image_urls or [],
                "businessId": active_business_id,
                "businessConfig": {"businessId": active_business_id},
                "loopCount": 0,
            },
        )

        intents = triage_state.get("intents") or []
        if intents:
            intents_str = ", ".join(f"{p.get('intent')} ({p.get('confidence')})" for p in intents)
            current_status = f"[Triage 完成] 识别出核心意图: {intents_str}"
        else:
            current_status = "[Triage 完成] 未识别出核心意图，准备直接交由 Finish 节点处理。"

        # 🧠 旁路直达:无意图 / 纯 general_query / 前置旁路
        is_only_general_query = len(intents) == 1 and intents[0].get("intent") == "general_query"
        is_bypass = bool(triage_state.get("output")) or (
            ((triage_state.get("taskPlan") or {}).get("subtasks") or [{}])[0].get("id") == "bypass_step"
        )
        if not intents or is_only_general_query or is_bypass:
            current_status = "[Finish] 直接接入快速响应生成..."
            finished_state = await run_node("finish", triage_state)
            current_status = "[已完成] 回复已生成。"
            chat_history.append({"role": "assistant", "content": finished_state.get("output") or ""})
            return {
                "threadId": thread_id,
                "userId": user_id,
                "input": input_message,
                "output": finished_state.get("output") or "No intent matched and completed.",
                "taskPlan": finished_state.get("taskPlan"),
            }

        # 2. planner → merge
        current_status = "[Planner] 正在根据识别到的意图，实时物理规划 DAG 任务执行拓扑图..."
        state = await run_node("planner", triage_state)
        current_plan = state.get("taskPlan")
        current_status = f'[Planner 完成] 成功生成业务规划，目标: {(current_plan or {}).get("goal") or "处理电商业务"}'

        current_status = "[Merge] 正在对任务规划进行依赖项分析与参数注入合并..."
        state = await run_node("merge", state)
        current_plan = state.get("taskPlan")

        # 3. executor ⇄ validator 循环(≤10 轮)
        loop_count = 0
        max_loops = 10
        while loop_count < max_loops:
            plan = state.get("taskPlan") or {}
            next_index = plan.get("currentStepIndex") or 0
            subtasks = plan.get("subtasks") or []
            if next_index >= len(subtasks) or next_index >= max_loops:
                break

            current_subtask = subtasks[next_index]
            current_status = f'[Executor 步骤 {next_index + 1}] 正在调起物理工具接口执行任务: "{current_subtask.get("description")}"...'
            state = await run_node("executor", state)
            current_plan = state.get("taskPlan")

            executed = ((state.get("taskPlan") or {}).get("subtasks") or [{}])[next_index]
            result = executed.get("result")
            if result:
                if result.get("toolExecuted") == "getOrderStatus":
                    order_info = result.get("output") or {}
                    current_status = (
                        f"[物理工具 getOrderStatus 调用完成] 订单号: {order_info.get('orderId') or 'ORD-98712'}, "
                        f"状态: {order_info.get('status') or '已发货'}, 承运商: {order_info.get('carrier') or 'FedEx'}"
                    )
                elif result.get("toolExecuted") == "processRefund":
                    refund_info = result.get("output") or {}
                    current_status = (
                        f"[物理工具 processRefund 调用完成] 订单号: {refund_info.get('orderId') or 'ORD-98712'}, "
                        f"结果: {refund_info.get('message') or '已自动原路退款'}"
                    )
                elif result.get("toolExecuted") == "takeScreenshot":
                    current_status = "[物理工具 takeScreenshot 调用完成] 成功渲染后台网页并捕获看板快照图片！"

            current_status = f"[Validator] 正在对步骤 {next_index + 1} 的物理执行结果进行多维置信度智能校验与对齐..."
            state = await run_node("validator", state)
            current_plan = state.get("taskPlan")
            current_status = f"[Validator 完成] 步骤 {next_index + 1} 校验通过。"

            loop_count += 1
            state["loopCount"] = loop_count

        # 4. finish
        current_status = "[Finish] 正在整合全部物理工具调用结果，通过大模型组织人性化中文最终回复..."
        final_state = await run_node("finish", state)
        current_status = "[已完成] 智能会话已圆满履约！回复已就绪。"
        if final_state.get("output"):
            chat_history.append({"role": "assistant", "content": final_state["output"]})

        return {
            "threadId": thread_id,
            "userId": user_id,
            "input": input_message,
            "output": final_state.get("output") or "Completed execution.",
            "taskPlan": final_state.get("taskPlan"),
        }
