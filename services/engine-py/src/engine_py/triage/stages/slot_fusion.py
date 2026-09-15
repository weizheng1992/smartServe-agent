"""🛡️ Step 1.5 意图与槽位完整性拦截(含多意图 / skill fast-track / 消歧)——
Stage(原 process 最大段,逐字搬移)。

槽位层全量抽取 → 复合多意图直达(多意图不打断)→ 单号信任边界与 OCR 注入 →
Step 1.6 破损图消歧 → 咨询形留痕 → 缺槽反问 → 资金否决让位 → 单意图
skill fast-track / slot_extractor 终局。异常诚实跳过槽位层裁决。
"""

from __future__ import annotations

from typing import Any

from ..intent_registry import AgentIntentType
from ..intent_triage_engine import (
    _MONEY_ACTION_INTENTS,
    _is_multi_intent_candidate,
    _money_action_vetoed,
    _proposal,
    _set_target_order_id,
)
from ..product_disambiguator import AFTER_SALE_INTENTS
from ..slot_extractor import ORDER_ID_RE
from .context import StageContext, StageVerdict


async def judge(ctx: StageContext) -> StageVerdict:
    state, input_text, thread_id, tenant_id = ctx.state, ctx.input_text, ctx.thread_id, ctx.tenant_id

    # 资金让位标记(多意图一期):规则层见资金词族但判成非资金意图时,判定 3
    # 关键词分支同样让位 —— 否则「推荐卫衣，帮我把上一单退掉」在 Step2 被
    # 吞成单退款,导购半静默丢失(与 money_action_veto_yield 同源)。
    money_action_yielded = False
    try:
        task_memory = ctx.ns.TaskMemory(thread_id)
        existing_task_state = await task_memory.get_task_state() or {}
        active_intent = existing_task_state.get("activeIntent")
        existing_slots = existing_task_state.get("slots") or {}
        existing_order_context = existing_task_state.get("orderContext") or state.get("order_context")

        # 已确认订单上下文同步进 state(2026-09-09):Step 2 各判定的单号
        # 融合与返回透传都以 state.order_context 为准,不同步则已确认单号
        # 在此轮丢失(甚至被图内 OCR 单号压过)
        if (existing_order_context or {}).get("targetOrderId") and not (
            (state.get("order_context") or {}).get("targetOrderId")
        ):
            _set_target_order_id(state, existing_order_context["targetOrderId"])

        context = {
            "orderContext": existing_order_context,
            "shortMemory": state.get("short_memory"),
            "historyMsgs": ctx.history_msgs,
        }

        all_specs = ctx.ns.SlotExtractor.extract_all(input_text, active_intent, existing_slots, context)

        if len(all_specs) >= 2:
            multi_intents: list[dict] = []
            for idx, spec in enumerate(all_specs):
                entry: dict[str, Any] = {
                    "intent": spec["intentType"],
                    "confidence": spec["confidence"],
                    "type": "primary" if idx == 0 else "secondary",
                    "taskSpec": spec,
                }
                if spec["slots"].get("orderId"):
                    entry["entities"] = {"orderId": str(spec["slots"]["orderId"])}
                multi_intents.append(entry)

            primary_order_id = next(
                (s["slots"]["orderId"] for s in all_specs if s["slots"].get("orderId")), None
            )
            if primary_order_id:
                _set_target_order_id(state, primary_order_id)

            await ctx.engine.log_intent_to_db(
                thread_id,
                input_text,
                multi_intents,
                "slot_extractor_multi",
                0.95,
                candidates=[
                    _proposal("slot_extractor", s["intentType"], s["confidence"]) for s in all_specs
                ],
                arbitration_reason="slot_extractor_multi",
            )
            return StageVerdict(
                terminal=True,
                result=await _terminal_with_order_context(ctx, multi_intents),
            )

        # extract_all 恒非空(detected≤1 时返回 [extract(...)]、≥2 时逐规则
        # 列表,且 ≥2 已在上分支返回),此处直接取首元素(工单02 死分支清理)
        task_spec = all_specs[0]

        # 单号信任边界(2026-09-10 误退事故第二层):slots.orderId 可能来自通用
        # extract_order_id 的历史反向回填 —— 历史最后提及的单号(旧消歧卡里的
        # 本店真单)只是续聊启发,不是用户本轮确认。它一旦进入 order_context,
        # refund 类判定(Step 2 判定 3 fused 的 confirmed 通道)与视觉消歧闸
        # (order_id_resolved)都会被短路:图内外店单 OCR 失效的轮次直接对历史
        # 单自动退款。文本显式与 TaskMemory 已确认才是可信通道;历史回填值
        # 留在 slots 供查询类续聊(ORDER_QUERY 快轨),不冒充已确认。
        text_order_match = ORDER_ID_RE.search(input_text)
        text_channel_order_id = text_order_match.group(0) if text_order_match else None
        confirmed_channel_order_id = (existing_order_context or {}).get("targetOrderId")
        trusted_order_id = text_channel_order_id or confirmed_channel_order_id
        if trusted_order_id:
            _set_target_order_id(state, trusted_order_id)

        # 图内 OCR 单号注入(2026-09-09 事故:ORD-77777 算完即丢)——单号优先级
        # 文本 > 已确认上下文 > 图内 OCR > 历史回填;注入后重跑槽位抽取,退款
        # 严格抽取器经 orderContext.targetOrderId 取到(与消歧 matched 注入同型)
        if ctx.vision_order_id and not trusted_order_id:
            _set_target_order_id(state, ctx.vision_order_id)
            context["orderContext"] = state["order_context"]
            task_spec = ctx.ns.SlotExtractor.extract(input_text, active_intent, existing_slots, context)

        # 槽位层提议入留痕(实体注入/消歧重抽取后取最终形态;后续各决策点
        # 的 candidates 以此为前缀,呈现「槽位判 X vs 锚点判 Y」的竞争原貌)
        ctx.proposals.append(_proposal("slot_extractor", task_spec["intentType"], task_spec["confidence"]))

        # 📷 Step 1.6: 破损图商品归属消歧(grilling 2026-09-09)——售后意图
        # 带图但缺 orderId(图内也无单号,OCR 通道失效)时,用 vision 摘要 ×
        # 近单商品行做 LLM 消歧,替代机械"请提供订单号"澄清:
        #   唯一高置信命中 → 注入 targetOrderId 并重跑槽位抽取(退款严格
        #     抽取器只认输入正则与该键,slot_extractor.py:72-82);
        #   多候选/低置信/模型失败 → 商品选择 quick_replies 卡片问用户;
        #   无候选订单 → 明示指引。消歧失败绝不炸会话,最坏多问一次。
        if ctx.engine._vision_disambig_due(
            state,
            ctx.vision_analysis,
            after_sale=task_spec["intentType"] in AFTER_SALE_INTENTS,
            # 文本通道单号(slots 可能携带历史回填值,不算已解析 —— 信任边界
            # 同上,2026-09-10 误退事故第二层;谓词本体另有 OCR/上下文通道)
            order_id_resolved=text_channel_order_id,
        ):
            disambig = await ctx.engine._run_vision_disambig(state, ctx.vision_analysis, tenant_id)
            if disambig["status"] == "matched":
                context["orderContext"] = state["order_context"]
                # 重跑槽位抽取:targetOrderId 已就位,本轮 slots 直接带上
                # orderId,免二次"请提供订单号"澄清;仍取不到则走下方正常澄清兜底
                task_spec = ctx.ns.SlotExtractor.extract(input_text, active_intent, existing_slots, context)
                ctx.proposals[-1] = _proposal(
                    "slot_extractor", task_spec["intentType"], task_spec["confidence"]
                )
            else:
                # 无候选/多候选两态收口(无候选明示指引,多候选出商品选择卡)
                return StageVerdict(
                    terminal=True,
                    result=await ctx.engine._vision_disambig_bypass(
                        state,
                        task_spec["intentType"],
                        task_spec["confidence"],
                        ctx.damage_assessment,
                        disambig,
                        candidates=list(ctx.proposals),
                    ),
                )

        # 🧭 冲突标记留痕(intent-arbitration 07,工单07 2026-09-11 挂点前移):
        # 槽位层判动作 × 咨询形措辞(疑问词×话题词×无动作动词)→ 记
        # consult_shaped_gate 提议。挂点自「槽位完整高置信终局」前移至缺槽
        # 反问检查之前 —— 07 追溯的靶形状正是咨询形输入被缺槽反问打断,
        # 旧挂点在该路径永不点亮,冲突信号源对此失明。路由不变(只记提议
        # 不碰 intents);信号只入池不成为断言(07 口径)。
        if task_spec["intentType"] != AgentIntentType.CHAT and ctx.ns.is_consult_shaped_marker(input_text):
            ctx.proposals.append(_proposal("consult_shaped_gate", AgentIntentType.CONSULT))

        # 多意图不打断(2026-09-12):复合候选形先行判定 —— 缺槽反问与单
        # 意图快轨都不得劫持复合轮,交结构化精判与 planner 编排。
        is_multi_intent_candidate = _is_multi_intent_candidate(input_text)

        # 高风险/多参数意图缺失必填槽位 → 即时追问,阻断死循环自旋。
        # 复合候选形除外(A3:「查订单把没发货的退了」被规则层「请提供
        # 订单编号」劫持,先查单再挑的合法流永远走不到 planner)。
        if (
            task_spec["missingSlots"]
            and task_spec["clarificationMessage"]
            and not is_multi_intent_candidate
        ):
            await task_memory.save_task_state(
                {
                    "goal": f"Fulfill {task_spec['intentType']}",
                    "subtasks": [],
                    "currentStepIndex": 0,
                    "activeIntent": task_spec["intentType"],
                    "slots": task_spec["slots"],
                    "orderContext": state.get("order_context"),
                    "guideContext": state.get("guide_context"),
                    "cartContext": state.get("cart_context"),
                }
            )
            return StageVerdict(
                terminal=True,
                result=await ctx.engine.handle_immediate_bypass(
                    state,
                    "slot_clarification_fastpath",
                    task_spec["clarificationMessage"],
                    [
                        {
                            "intent": task_spec["intentType"],
                            "confidence": task_spec["confidence"],
                            "taskSpec": task_spec,
                        }
                    ],
                    "slot_extractor",
                    task_spec["confidence"],
                    ctx.damage_assessment,
                    candidates=list(ctx.proposals),
                ),
            )

        # 参数齐备且非复合多意图 → 高置信度放行进入 DAG 调度
        if (
            not is_multi_intent_candidate
            and task_spec["intentType"] != "chat"
            and not task_spec["missingSlots"]
            and task_spec["confidence"] >= 0.8
        ):
            # 🚦 资金否决让位(多意图一期,2026-09-12,评审缺陷②):规则层只
            # 检出导购/购物车单意图(资金词族不在其规则 pattern 里,如「退掉」)
            # 时,连单意图终局一起让位 Step2/3 精判并留痕 —— 否则「推荐几款
            # 卫衣，帮我把上一单退掉」照样以 single_complete 吞掉退款半。
            if (
                _money_action_vetoed(input_text)
                and task_spec["intentType"] not in _MONEY_ACTION_INTENTS
            ):
                yield_intents = [
                    {
                        "intent": task_spec["intentType"],
                        "confidence": task_spec["confidence"],
                        "type": "primary",
                        "taskSpec": task_spec,
                    }
                ]
                await ctx.engine.log_intent_to_db(
                    thread_id,
                    input_text,
                    yield_intents,
                    "rule",
                    task_spec["confidence"],
                    candidates=list(ctx.proposals),
                    arbitration_reason="money_action_veto_yield",
                )
                money_action_yielded = True
            else:
                intents = [
                    {
                        "intent": task_spec["intentType"],
                        "confidence": task_spec["confidence"],
                        "taskSpec": task_spec,
                    }
                ]

                await task_memory.save_task_state(
                    {
                        "goal": f"Completed {task_spec['intentType']}",
                        "subtasks": [],
                        "currentStepIndex": 0,
                        "activeIntent": None,
                        "slots": task_spec["slots"],
                        "orderContext": state.get("order_context"),
                        "guideContext": state.get("guide_context"),
                        "cartContext": state.get("cart_context"),
                    }
                )

                # 🎯 Skill Fast-Track 直达极速执行(skills 包落地后自动激活)。
                # 终局决策单点落库(01):fast-track 命中时以 bypass 内的写为准
                # (method=skill_fast_track,candidates 含槽位+技能两提议);
                # 未命中才在下方落 slot_extractor 行 —— 修复同一输入双写。
                fast_track = await ctx.engine._try_skill_fast_track(
                    state,
                    thread_id,
                    tenant_id,
                    task_spec,
                    ctx.history_msgs,
                    ctx.damage_assessment,
                    intents,
                    ctx.proposals,
                )
                if fast_track is not None:
                    return StageVerdict(terminal=True, result=fast_track)

                await ctx.engine.log_intent_to_db(
                    thread_id,
                    input_text,
                    intents,
                    "slot_extractor",
                    task_spec["confidence"],
                    candidates=list(ctx.proposals),
                    arbitration_reason="slot_extractor_single_complete",
                )

                # 单号上下文透传(2026-09-15 查单关联断链收口):本终局是全
                # 引擎唯一漏带 with_order_context 的出口 —— 查单轮解析出的
                # targetOrderId 只落在原地 state,不进 LangGraph 通道,run_agent
                # 收口「result or 回合初快照」双空把 ctx.ns.TaskMemory.orderContext
                # 覆空,下一轮资金动作严格抽取器读不到已确认单号,冷启动追问
                # (实弹:刚查完 9094 说「我想申请退款」被反问订单编号)。
                # 此处 state.order_context 只含可信通道值(文本显式/已确认
                # 上下文/图内 OCR,见 869-880 信任边界),透传不泄漏历史盲回填。
                return StageVerdict(terminal=True, result=await _terminal_with_order_context(ctx, intents))
    except Exception as slot_err:
        import traceback
        traceback.print_exc()
        print(f"[Triage] 槽位澄清阶段异常,已跳过槽位层裁决 (threadId={thread_id}): {slot_err}")

    ctx.flags["money_action_yielded"] = money_action_yielded
    return StageVerdict.passthrough()


async def _terminal_with_order_context(ctx: StageContext, intents: list[dict]) -> dict:
    from ..intent_triage_engine import _triage_terminal_result

    return _triage_terminal_result(
        intents,
        ctx.input_text,
        ctx.history_msgs,
        ctx.damage_assessment,
        state=ctx.state,
        with_order_context=True,
    )
