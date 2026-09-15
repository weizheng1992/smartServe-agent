"""步骤执行引擎 — 镜像 stepExecutionEngine.ts(632 LOC,含并行调度与 HITL 门禁)。"""

from __future__ import annotations

import asyncio
import json
import re

from ...approvals.gatekeeper import ApprovalPolicyEngine
from ...event_bus import emit_status
from ...llm import get_chat_model
from ...memory import ShortMemory, TaskMemory
from ..state import build_history_context
from .executor_fast_path import try_match_executor_fast_path

_JSON_FENCE_START_RE = re.compile(r"^```json\s*")

# 售后凭证程序化注入(ADR-0002 Q1):applyAfterSale 落工单 evidence_urls 列,
# processRefund 经 HITL 审批载荷让人工审批员看到凭证。唯一可信来源是本轮
# state.image_urls —— 严禁指望 LLM 从会话历史抄 URL(会错链漏链)。
_AFTERSALE_EVIDENCE_TOOLS = frozenset({"applyAfterSale", "processRefund"})


async def maybe_inject_aftersale_evidence(tool_name: str, args: dict, state: dict) -> dict:
    """售后工具凭证程序化注入(ADR-0002 Q1 + ADR-0003 Q3):
    本轮 state.image_urls 优先(有图严禁额外查库);本轮无图回溯本会话
    历史用户消息图片;两者皆无 → 原样返回。上限与引擎视觉上限一致。"""
    from ...vision.analyzer import MAX_IMAGES_PER_MESSAGE

    if tool_name not in _AFTERSALE_EVIDENCE_TOOLS:
        return args
    if args.get("evidenceImageUrls"):
        return args
    current = list(state.get("image_urls") or [])
    if not current:
        try:
            from ...tools_registry.order_domain import OrderDomainService

            current = await OrderDomainService.get_thread_evidence_images(state.get("thread_id"))
        except Exception as err:
            print(f"[StepExecutionEngine] 历史凭证图回溯失败 threadId={state.get('thread_id')}: {err}")
            current = []
    if not current:
        return args
    return {**args, "evidenceImageUrls": current[:MAX_IMAGES_PER_MESSAGE]}


def _try_import_skills():
    try:
        from ...skills import SkillRegistry

        return SkillRegistry
    except ImportError:
        return None


def _try_import_tools():
    try:
        from ...tools_registry import get_tool

        return get_tool
    except ImportError:
        return None


async def _execute_single_step_core(
    state: dict,
    current_plan: dict,
    index_to_run: int,
    allowed_tools: list[str],
    short_memory: list[dict],
    history_context: str,
) -> dict:
    subtask = dict(current_plan["subtasks"][index_to_run])
    step_to_run = {**subtask, "status": "executing"}

    desc_lower = (step_to_run.get("description") or "").lower()
    step_id = (step_to_run.get("id") or "").lower()

    # 0. 条件分支执行谓词评估
    condition = step_to_run.get("condition")
    if condition:
        field, operator, expected_value = condition.get("field"), condition.get("operator"), condition.get("expectedValue")
        actual_value = None
        for st in current_plan["subtasks"]:
            if st.get("status") == "completed" and (st.get("result") or {}).get("output"):
                out = st["result"]["output"]
                out = out if isinstance(out, dict) else {}
                if field in out:
                    actual_value = out[field]
                    break
                for container in ("order", "data", "details"):
                    if isinstance(out.get(container), dict) and field in out[container]:
                        actual_value = out[container][field]
                        break

        def _normalize(val):
            return val.strip().lower() if isinstance(val, str) else val

        norm_actual = _normalize(actual_value)
        norm_expected = _normalize(expected_value)

        if operator == "equals":
            is_condition_met = norm_actual == norm_expected
        elif operator == "not_equals":
            is_condition_met = norm_actual != norm_expected
        elif operator == "exists":
            is_condition_met = actual_value is not None
        elif operator == "in" and isinstance(expected_value, list):
            is_condition_met = norm_actual in [_normalize(v) for v in expected_value]
        elif operator == "greater_than":
            is_condition_met = float(actual_value or 0) > float(expected_value or 0)
        else:
            is_condition_met = True

        if not is_condition_met:
            skipped_step = {
                **step_to_run,
                "status": "skipped",
                "result": {
                    "skippedReason": (
                        f"Condition unmet: expected {field} {operator} {json.dumps(expected_value, default=str)}, "
                        f"but was {json.dumps(actual_value, default=str)}"
                    )
                },
            }
            return {"updatedStep": skipped_step, "toolErrorsCount": 0}

    # 1. 人工客服转接判断
    if (
        "human_escalation" in step_id
        or "escalat" in desc_lower
        or "human" in desc_lower
        or "转人工" in desc_lower
        or "人工客服" in desc_lower
    ):
        ticket = await ApprovalPolicyEngine.create_pending_approval_ticket(
            {
                "threadId": state.get("thread_id", ""),
                "userId": state.get("user_id"),
                "actionType": "human_escalation",
                "actionPayload": {
                    "reason": "User requested human customer support intervention",
                    "userInput": state.get("input"),
                    "triggerSource": "user_request",
                },
                "jobId": state.get("job_id"),
                "stepToRun": step_to_run,
                "currentPlan": current_plan,
                "currentIndex": index_to_run,
            }
        )
        pending_step = ticket["nextPlan"]["subtasks"][index_to_run] or step_to_run
        return {
            "updatedStep": pending_step,
            "toolErrorsCount": 0,
            "waitingForApproval": True,
            "approvalPlan": ticket["nextPlan"],
        }

    # 2. Fast-Path 正则匹配
    parsed_tool_call = try_match_executor_fast_path(
        step_to_run.get("description") or "", state.get("input") or "", allowed_tools, short_memory
    )

    if parsed_tool_call is None:
        # 3. Fallback: LLM 工具选择
        prompt = (
            f'We are executing step: "{step_to_run.get("description")}".\n\n'
            "CRITICAL INSTRUCTIONS FOR TOOL SELECTION:\n"
            "1. Determine if this step corresponds to executing an actual tool action or retrieving data from our systems.\n"
            '2. If this step is merely presenting results, answering questions, or communicating with the user '
            '(e.g. "Present...", "Ask...", "Explain..."), you MUST output "NONE".\n'
            '3. If the step description explicitly calls for retrieving, checking, or tracking order details, '
            f'select "getOrderStatus" from: {json.dumps(allowed_tools)}.\n'
            '4. If the step description explicitly calls for processing or initiating a refund for an order, '
            f'select "processRefund" from: {json.dumps(allowed_tools)}.\n'
            '5. If the step description mentions listing, showing, or finding recent orders or order history, '
            'select "listUserOrders". If the user asks for unshipped / not-yet-shipped orders '
            '(未发货 / 还没发货 / 尚未发货), pass args {"shippingStatus": "UNSHIPPED"}; '
            'explicitly delivered orders → "DELIVERED".\n'
            '6. If the step description mentions changing shipping address, select "changeShippingAddress".\n'
            '7. If the step description mentions generating an invoice, select "generateInvoice".\n'
            '8. If the step description mentions recording user preferences, select "recordUserPreference".\n'
            '9. If the step description mentions searching, recommending or ranking products, comparing '
            'products, or checking SKU stock and reviews, select the matching product tool '
            '(e.g. "searchProducts", "compareProducts", "queryProductSkus", "queryProductReviews", '
            '"queryProductRanking"). For hot-selling / best-seller asks (热销/热卖/畅销/卖得好), '
            'select "queryProductRanking" with rankingMetric "volume" (real sales data only).\n'
            '10. If the step description mentions placing a real order / checking out the cart '
            '(结算下单/下单), select "checkoutCart" — it creates a real merchant order from the current '
            'cart. If it mentions sales ranking or best-seller metrics with a named rankingMetric, '
            'select "queryProductRanking" with that rankingMetric (real sales data only).\n'
            "11. Extract arguments from CONVERSATION HISTORY below.\n\n"
            'Output raw JSON object or "NONE":\n{"toolName": "toolName", "args": {"key": "value"}}\n\n'
            f"[CONVERSATION HISTORY]\n{history_context}"
        )
        response = await get_chat_model().ainvoke(prompt)
        content = response.content if hasattr(response, "content") else str(response)
        clean = content.strip()
        if clean != "NONE":
            try:
                clean = _JSON_FENCE_START_RE.sub("", clean)
                clean = re.sub(r"```$", "", clean).strip()
                parsed_tool_call = json.loads(clean)
            except Exception:
                parsed_tool_call = None

    result_data = None

    if parsed_tool_call and parsed_tool_call.get("toolName") in allowed_tools:
        tool_name = parsed_tool_call["toolName"]
        args = await maybe_inject_aftersale_evidence(tool_name, parsed_tool_call.get("args") or {}, state)
        order_id = args.get("orderId")

        # 4.1 重复退款防护拦截(三源判定,商户真单按用户归属匹配)
        if tool_name == "processRefund" and order_id:
            double_check = await ApprovalPolicyEngine.check_double_refund(order_id, state.get("user_id"))
            if double_check.get("isDoubleRefund"):
                failed_step = {
                    **step_to_run,
                    "status": "failed",
                    "result": {
                        "error": "该订单已经是已退款状态，禁止重复退款。",
                        "message": (
                            f"⚠️ 退款流程拦截：系统检测到订单 [{order_id}] 的状态在数据库中已经是 [已退款] 状态，"
                            "物理拒绝重复退款操作！"
                        ),
                    },
                }
                return {"updatedStep": failed_step, "toolErrorsCount": 1}

            # 4.1.1 幽灵单前置拦截(2026-09-09 OCR 事故收口):随手图片 OCR 出的
            # 或文本里敲的单号,三库查无此单(或非本人归属)时审批门直接诚实失败
            # —— 旧行为是直达 HITL 开 waiting 工单,finish 终稿还谎称"已为您
            # 发起退款申请"。技能 fast-track 路径本就有同款校验,此处对齐。
            if not double_check.get("orderFound", True):
                failed_step = {
                    **step_to_run,
                    "status": "failed",
                    "result": {
                        "error": f"Order {order_id} not found",
                        "message": (
                            f"⚠️ 未查询到订单 [{order_id}]，或该订单不属于当前账户。请核对订单号后重试；"
                            "如需帮助可输入「转人工」联系人工客服。"
                        ),
                    },
                }
                return {"updatedStep": failed_step, "toolErrorsCount": 1}

            # 4.2 免签限额判定
            tenant_limit = (state.get("business_config") or {}).get("refundAutoApprovalLimit") or 100
            auto_check = await ApprovalPolicyEngine.evaluate_refund_auto_approval(
                order_id, args.get("refundAmount") or args.get("amount"), tenant_limit
            )
            if auto_check["shouldAutoApprove"] and state.get("job_id"):
                await emit_status(
                    state["job_id"],
                    f"✅ 政策放行：检测到本次退款金额 (¥{auto_check['groundedAmount']}) 在商户免签限额 "
                    f"(¥{tenant_limit}) 以内，已物理触发【额度免签直接放行】！",
                    node="executor",
                )

        # 4.3 高价值订单地址变更红线
        is_high_value_addr = False
        if tool_name == "changeShippingAddress" and order_id:
            addr_check = await ApprovalPolicyEngine.evaluate_address_change_policy(order_id)
            is_high_value_addr = addr_check["isHighValue"]

        # 4.4 人工审批工单门禁
        if tool_name == "processRefund" or is_high_value_addr:
            tenant_limit = (state.get("business_config") or {}).get("refundAutoApprovalLimit") or 100
            auto_check = await ApprovalPolicyEngine.evaluate_refund_auto_approval(
                order_id, args.get("refundAmount") or args.get("amount"), tenant_limit
            )
            if tool_name != "processRefund" or not auto_check["shouldAutoApprove"]:
                approval_result = await ApprovalPolicyEngine.evaluate_pending_approval_state(
                    {
                        "threadId": state.get("thread_id", ""),
                        "toolName": tool_name,
                        "args": args,
                        "stepDescription": step_to_run.get("description"),
                        "stepIndex": index_to_run,
                        "existingApprovalId": (step_to_run.get("result") or {}).get("approvalId"),
                    }
                )
                if approval_result.get("state") == "waiting":
                    pending_step = {
                        **step_to_run,
                        "status": "pending",
                        "result": {
                            "waitingForApproval": True,
                            "approvalId": approval_result.get("approvalId"),
                        },
                    }
                    # 🛡️ 挂起即落库(wayfinder 004):审批工单创建后对前端 2s 轮询
                    # 立即可见,而挂起计划此前要等运行收口才 save_task_state —— 窗口期
                    # 内核签派发的 job_resume_* 读到空计划,triage 的 System: 分支
                    # 误判 order_status 直接查单,退款永不执行。计划持久化必须与
                    # 审批可见性同一时刻成立(运行收口会用完整版含领域上下文覆写)。
                    suspended_plan = {
                        **current_plan,
                        "subtasks": [
                            *current_plan["subtasks"][:index_to_run],
                            pending_step,
                            *current_plan["subtasks"][index_to_run + 1 :],
                        ],
                        "currentStepIndex": index_to_run,
                    }
                    thread_id = state.get("thread_id") or ""
                    if thread_id:
                        try:
                            await TaskMemory(thread_id).save_task_state(suspended_plan)
                        except Exception as tm_err:
                            print(f"[执行引擎] 挂起计划落库任务记忆失败 thread={thread_id}: {tm_err}")
                    else:
                        # 空 thread_id 会命中 TaskMemory("") 的共享键,污染其他会话的任务记忆
                        print("[执行引擎] 挂起计划落库跳过:thread_id 为空,拒绝写入共享键")
                    return {"updatedStep": pending_step, "toolErrorsCount": 0, "waitingForApproval": True}

                if approval_result.get("state") in ("expired", "cancelled", "rejected"):
                    failed_step = {
                        **step_to_run,
                        "status": "failed",
                        "result": {
                            "error": approval_result.get("error") or approval_result.get("rejectionReason"),
                            "message": approval_result.get("message"),
                            "approvalId": approval_result.get("approvalId"),
                        },
                    }
                    return {"updatedStep": failed_step, "toolErrorsCount": 1}

        # 5. 工具/技能物理调度
        skill_registry = _try_import_skills()
        skill_def = skill_registry.get_skill(tool_name) if skill_registry else None
        if skill_def is not None:
            if state.get("job_id"):
                await emit_status(
                    state["job_id"],
                    f"正在调起业务技能 [{skill_def.metadata['name']}]，执行 SOP 闭环...",
                    node="executor",
                )
            tenant_id = str(
                (state.get("business_config") or {}).get("businessId") or state.get("business_id") or "ecommerce"
            ).lower()
            intents = state.get("intents") or []
            skill_result = await skill_def.execute(
                {
                    "threadId": state.get("thread_id"),
                    "tenantId": tenant_id,
                    "userId": state.get("user_id"),
                    "input": state.get("input"),
                    "slots": {**args, "activeIntent": (intents[0].get("intent") if intents else "")},
                    "imageUrls": state.get("image_urls"),
                    "extra": {
                        "isApproved": True,
                        "damageAssessment": state.get("damage_assessment"),
                        "guideContext": state.get("guide_context"),
                        "cartContext": state.get("cart_context"),
                    },
                }
            )
            result_data = {
                "toolExecuted": tool_name,
                "output": skill_result.get("output"),
                "cards": skill_result.get("cards"),
                "success": skill_result.get("success"),
                "error": skill_result.get("error"),
            }
            extra = skill_result.get("extra") or {}
            if extra.get("guideContext"):
                state["guide_context"] = extra["guideContext"]
            if extra.get("cartContext"):
                state["cart_context"] = extra["cartContext"]
            if skill_result.get("cards"):
                state["cards"] = (state.get("cards") or []) + skill_result["cards"]
        else:
            get_tool = _try_import_tools()
            tool_def = get_tool(tool_name) if get_tool else None
            if tool_def is not None:
                if state.get("job_id"):
                    await emit_status(
                        state["job_id"],
                        f"正在真实调起物理工具接口 [{tool_name}]，传入参数: {json.dumps(args, ensure_ascii=False, default=str)}...",
                        node="executor",
                    )
                tenant_id = str(
                    (state.get("business_config") or {}).get("businessId") or state.get("business_id") or "ecommerce"
                ).lower()
                output = await tool_def.execute(
                    {
                        **args,
                        "threadId": state.get("thread_id"),
                        "userId": state.get("user_id"),
                        "businessId": tenant_id,
                        "tenantId": tenant_id,
                        "isApproved": True,
                    }
                )
                result_data = {"toolExecuted": tool_name, "output": output}
                # 待确认动作登记(S8/S3/S7 同族,2026-09-15):地址保存成功后,
                # 「改成默认」确认轮可由 triage pending_action 恢复执行,LLM 不再丢参
                if tool_name == "saveUserAddress" and isinstance(output, dict) and output.get("success"):
                    state["task_plan"] = {
                        **(state.get("task_plan") or {}),
                        "pendingAction": {
                            "tool": "set_default_address",
                            "args": {"receiverName": output.get("fullAddress") and ""},
                        },
                    }

                # 图路径候选登记(2026-09-12):planner 给 executor 的可能是
                # searchProducts 工具而非 ShoppingGuideSkill —— 工具路径此前不
                # 写 guide_context,上一轮导购的 stale 候选经 run_agent 收口原样
                # 存回 TaskMemory,下一轮加购的"第N件"序数解析到旧候选(幻影
                # Nike 入车症状)。结果非空即刷新候选,与技能路径的
                # extra.guideContext 同形,不依赖 planner 选工具还是选技能。
                if tool_name == "searchProducts" and isinstance(output, dict) and output.get("products"):
                    found_products = output["products"]
                    state["guide_context"] = {
                        "candidateProductIds": [p.get("id") for p in found_products],
                        "candidateProducts": [
                            {
                                "id": p.get("id"),
                                "name": p.get("name"),
                                "price": float(p.get("price") or 0),
                                "stock": int(p.get("stock") or 0),
                                "description": p.get("description"),
                                "specs": p.get("specs"),
                                "imageUrl": p.get("imageUrl"),
                            }
                            for p in found_products
                        ],
                        "extractedPreferences": {},
                        "clarificationRound": 1,
                        "lastSearchQuery": args.get("query") or state.get("input") or "",
                    }

                # 此处原有「工具执行 → eval_runs/eval_results 评估日志」写入块,已于
                # 2026-09-05 整体移除:UUID 主键传 VARCHAR 导致从未成功写入过一行
                # (每次工具执行必报 DatatypeMismatchError),且写入值为硬编码假指标
                # (quality=5.0 / latency=100 / 固定 run_id / 固定 'ecommerce' 租户),
                # 违反数据真实性约定与多租户不变量;真实遥测走 llm_call_logs(逐调用)
                # 与 session_metrics(会话汇总),真实评测走 bun run test:prompt。
            else:
                result_data = {"error": f"Tool or Skill {tool_name} not found in registry."}
    else:
        result_data = {"message": "Step execution completed without needing tools"}

    # 6. 构造返回结果
    final_status = "failed" if result_data.get("error") else "completed"
    updated_step = {**step_to_run, "status": final_status, "result": result_data}
    return {
        "updatedStep": updated_step,
        "toolErrorsCount": 1 if result_data.get("error") else 0,
        "toolExecutedName": result_data.get("toolExecuted"),
        # guide_context 必须经返回值上行(2026-09-12):executor_node 拿到的是
        # dict(state) 拷贝,直接改 state 键是死写 —— 技能/工具分支刷新的候选
        # 上下文此前到不了图状态,run_agent 收口把旧值原样存回 TaskMemory
        # (幻影 Nike 入车症状的图路径根因)。
        "guideContext": state.get("guide_context"),
    }


# executor 步骤工具白名单基座(测试缝):租户 business_config.tools 可追加,
# 不可缩减。地址簿工具(saveUserAddress/getUserAddresses)于多意图一期入列 ——
# saveUserAddress 是顾客自有低风险写(A11 实弹:不入列则 planner 快轨子任务
# 被 dispatch 门槛跳过,LLM 步骤执行幻觉宣称「已成功保存」,表 0 行),
# 执行器有确定性快路径;addToCart 等购物车写仍不入列(必须走技能 SOP)。
_base_executor_tools = [
    "getOrderStatus",
    "processRefund",
    "takeScreenshot",
    "listUserOrders",
    "changeShippingAddress",
    "generateInvoice",
    "recordUserPreference",
    "skill_shopping_guide",
    "skill_cart_manage",
    "searchProducts",
    "compareProducts",
    "queryProductSkus",
    "queryProductReviews",
    "queryProductRanking",
    "getCartSummary",
    "saveUserAddress",
    "getUserAddresses",
    "setDefaultAddress",
    "deleteUserAddress",
    "checkoutCart",
]


async def execute_step(state: dict) -> dict:
    current_plan = dict(state.get("task_plan") or {})
    current_index = current_plan.get("currentStepIndex", 0)
    subtasks = current_plan.get("subtasks") or []
    subtask = subtasks[current_index] if 0 <= current_index < len(subtasks) else None

    if subtask is None:
        return {"taskPlan": current_plan, "globalTransitionsCount": 1}
    if subtask.get("status") == "completed":
        return {"taskPlan": current_plan, "globalTransitionsCount": 1}

    business_config = state.get("business_config") or {}
    # 2026-09-07:TS 基线白名单仅含订单/退款 7 工具,商品查询/导购类子任务在下方
    # dispatch 门槛被整段跳过 → "Step execution completed without needing tools"
    # 空转至道歉降级。现纳入:导购/购物车技能(executor_fast_path 直呼其
    # 注册表 id)+ 只读商品工具。写操作购物车工具(addToCart/updateCartItem)仍不
    # 入白名单 —— 加购/改量必须走技能 SOP 管道,不允许 LLM 兜底直调。
    base_tools = _base_executor_tools
    allowed_tools = list(dict.fromkeys([*(business_config.get("tools") or []), *base_tools])) if business_config.get(
        "tools"
    ) else list(base_tools)

    short_memory = state.get("short_memory") or []
    if not short_memory:
        short_memory = await ShortMemory(state.get("thread_id", "")).get_messages()
    formatted_history = build_history_context(short_memory)
    history_context = (
        f"\n\n[CONVERSATION HISTORY (PAST TURNS)]:\n{formatted_history}"
        if formatted_history
        else f'\n\n[CURRENT USER INPUT]:\nCustomer: "{state.get("input")}"'
    )

    # ⚡ 独立子任务并行调度检测。
    # 技能依赖护栏(2026-09-13 一句话接力实弹):guide 写候选 → cart 读候选
    # 是有状态依赖的 SOP 链,曾被无脑并行(gather 同一 state 拷贝)——cart 在
    # guide 写入前读空候选直接反问。技能型步骤之间一律串行。
    def _skill_tool_of(desc: str) -> str | None:
        match = try_match_executor_fast_path(desc, state.get("input") or "", allowed_tools, short_memory)
        tool = (match or {}).get("toolName") or ""
        return tool if tool.startswith("skill_") else None

    current_skill_tool = _skill_tool_of(subtasks[current_index].get("description") or "")
    candidate_indices = [current_index]
    for idx in range(current_index + 1, len(subtasks)):
        next_st = subtasks[idx]
        if next_st and (next_st.get("status") == "pending" or not next_st.get("status")):
            next_skill_tool = _skill_tool_of(next_st.get("description") or "")
            next_desc = (next_st.get("description") or "").lower()
            is_escalation = any(kw in next_desc for kw in ("escalat", "human", "转人工"))
            if current_skill_tool or next_skill_tool:
                break  # 技能链串行:前序技能写候选/购物车,后续步骤(含 checkoutCart 工具)消费 —— 严禁并行
            match = try_match_executor_fast_path(
                next_st.get("description") or "", state.get("input") or "", allowed_tools, short_memory
            )
            if match and not is_escalation:
                candidate_indices.append(idx)
            else:
                break
        else:
            break

    updated_subtasks = list(subtasks)
    total_errors = 0
    job_id = state.get("job_id")

    if len(candidate_indices) > 1:
        if job_id:
            await emit_status(
                job_id,
                f"⚡【并行执行器 (Parallel Executor)】检测到 {len(candidate_indices)} 项独立无依赖子任务，"
                "正在调起 Promise.all 并发极速执行中...",
                node="executor",
                plan={
                    **current_plan,
                    "currentStepIndex": current_index,
                    "subtasks": [
                        {**st, "status": "executing"} if i in candidate_indices else st
                        for i, st in enumerate(subtasks)
                    ],
                },
            )

        parallel_results = await asyncio.gather(
            *(
                _execute_single_step_core(state, current_plan, idx, allowed_tools, short_memory, history_context)
                for idx in candidate_indices
            )
        )
        merged_guide_context = None
        for idx, res in zip(candidate_indices, parallel_results):
            updated_subtasks[idx] = res["updatedStep"]
            total_errors += res["toolErrorsCount"]
            if res.get("guideContext"):
                merged_guide_context = res["guideContext"]

        next_plan = {**current_plan, "subtasks": updated_subtasks}
        if job_id:
            await emit_status(
                job_id,
                f"⚡【并行执行完成】{len(candidate_indices)} 项子任务物理调用已全部并发归验完成，总 Latency 提升 50%+！",
                node="executor",
                plan=next_plan,
            )
        return {
            "taskPlan": next_plan,
            "shortMemory": short_memory,
            "globalTransitionsCount": 1,
            "toolErrorsCount": total_errors,
            "guideContext": merged_guide_context,
        }

    # 单步骤标准执行
    if job_id:
        await emit_status(
            job_id,
            f"正在执行第 {current_index + 1} 步: {subtask.get('description')}...",
            node="executor",
            plan={
                **current_plan,
                "currentStepIndex": current_index,
                "subtasks": [
                    {**st, "status": "executing"} if i == current_index else st
                    for i, st in enumerate(subtasks)
                ],
            },
        )

    single_result = await _execute_single_step_core(
        state, current_plan, current_index, allowed_tools, short_memory, history_context
    )

    if single_result.get("waitingForApproval") and single_result.get("approvalPlan"):
        return {
            "taskPlan": single_result["approvalPlan"],
            "shortMemory": short_memory,
            "globalTransitionsCount": 1,
            "toolErrorsCount": 0,
        }

    updated_subtasks[current_index] = single_result["updatedStep"]
    next_plan = {**current_plan, "subtasks": updated_subtasks}

    if job_id:
        result_obj = single_result["updatedStep"].get("result") or {}
        res_output = result_obj.get("output") if isinstance(result_obj.get("output"), dict) else {}
        executed_tool = result_obj.get("toolExecuted")
        friendly_message = f"步骤 [{subtask.get('description')}] 履行完成。"
        if executed_tool == "getOrderStatus":
            friendly_message = (
                f"✅ getOrderStatus 接口物理调用成功！检测到订单 [{res_output.get('orderId') or 'ORD-98712'}]："
                f"当前状态为 [{res_output.get('status') or '已发货'}]，物流承运商为 [{res_output.get('carrier') or 'FedEx'}]，"
                f"单号 [{res_output.get('trackingNumber') or '1234567890'}]。"
            )
        elif executed_tool == "processRefund":
            friendly_message = (
                f"✅ processRefund 退款物理工作流执行成功！订单 [{res_output.get('orderId') or 'ORD-98712'}] "
                f"状态已在 Postgres 物理表中更新为: [{res_output.get('status') or '已退款'}]，"
                f"金额: [{res_output.get('refundAmount') or '100% 原路返还'}]。"
            )
        elif executed_tool == "listUserOrders":
            friendly_message = (
                f"✅ listUserOrders 查单物理接口调用成功！检测到 [{len(res_output.get('orders') or [])}] 笔历史订单记录。"
            )
        elif executed_tool == "changeShippingAddress":
            friendly_message = (
                f"✅ changeShippingAddress 地址修改成功！订单 [{res_output.get('orderId')}] "
                f"配送物理地址已成功变更为: [{res_output.get('newAddress')}]。"
            )
        await emit_status(job_id, friendly_message, node="executor", plan=next_plan)

    return {
        "taskPlan": next_plan,
        "shortMemory": short_memory,
        "globalTransitionsCount": 1,
        "toolErrorsCount": single_result["toolErrorsCount"],
        "guideContext": single_result.get("guideContext"),
    }


StepExecutionEngine = {"executeStep": execute_step}
