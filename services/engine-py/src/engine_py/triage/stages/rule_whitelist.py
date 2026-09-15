"""🛡️ Step 1 规则白名单 + 空输入/符号/超长预过滤 — Stage(原 process 段,逐字搬移)。

问候/退出指令消费租户 onboarding_config 同源罐头;空消息、纯符号、超长输入
零 LLM 旁路;人工升级请求直达终局。
"""

from __future__ import annotations

from .. import rule_matchers
from .context import StageContext, StageVerdict


async def judge(ctx: StageContext) -> StageVerdict:
    state, input_text = ctx.state, ctx.input_text

    # 🛡️ Step 0: 输入格式预过滤
    if not input_text and not state.get("image_urls"):
        reply = "您好！看起来您发送了一条空消息。请问有什么我可以帮您的？"
        return StageVerdict(
            terminal=True,
            result=await ctx.engine.handle_immediate_bypass(state, "rule_empty", reply, [], "rule", 1.0),
        )

    if rule_matchers.is_symbol_only(input_text):
        reply = "您好！如果您有关于订单、物流或退款方面的疑问，可以直接向我提问，我将为您竭诚服务。"
        return StageVerdict(
            terminal=True,
            result=await ctx.engine.handle_immediate_bypass(state, "rule_symbols", reply, [], "rule", 1.0),
        )

    if len(input_text) > 1000:
        reply = "您好！您发送的内容过长，系统暂时无法解析。请问您有具体的订单或退款问题需要我协助吗？"
        return StageVerdict(
            terminal=True,
            result=await ctx.engine.handle_immediate_bypass(
                state, "rule_length_limit", reply, [], "rule", 1.0
            ),
        )

    if rule_matchers.is_human_escalation_requested(input_text):
        intents = [{"intent": "human_escalation", "confidence": 1.0}]
        return StageVerdict.terminal(ctx, intents)

    # 🛡️ Step 1: 规则白名单
    if rule_matchers.is_greeting(ctx.clean_input):
        # 同源改造(new-user-onboarding D):罐头回复消费租户 onboarding_config
        # (与建线程欢迎行/引擎极速旁路同一份),入口卡一并下发;零 LLM 与
        # 仲裁留痕口径不变(rule_greeting 路由键、candidates 记录)。
        onboarding = await ctx.ns.resolve_onboarding_config(ctx.tenant_id)
        return StageVerdict(
            terminal=True,
            result=await ctx.engine.handle_immediate_bypass(
                state,
                "rule_greeting",
                onboarding["welcomeText"],
                [{"intent": "general_query", "confidence": 1.0}],
                "rule",
                1.0,
                cards=ctx.ns.build_entry_cards(onboarding),
            ),
        )

    if rule_matchers.is_exit_command(ctx.clean_input):
        reply = (
            "好的，很高兴为您服务！如果您后续还有任何关于订单状态或退款方面的需要，"
            "欢迎随时联系我。祝您生活愉快，再见！👋"
        )
        return StageVerdict(
            terminal=True,
            result=await ctx.engine.handle_immediate_bypass(
                state, "rule_exit_conversation", reply, [{"intent": "general_query", "confidence": 1.0}], "rule", 1.0
            ),
        )

    return StageVerdict.passthrough()
