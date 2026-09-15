"""🛡️ 重复提问拦截器 — Stage 3(原 process 段,逐字搬移)。

完全相同/语义相似(≥0.98 且数字指纹一致)的重复提问重放上一条 AI 答复;
上一答复失败或含未消毒标签时不拦截。带图轮次豁免(2026-09-10 误退事故:
图证是新证据,先于文本去重被消费会重放旧消歧卡)。
"""

from __future__ import annotations

import asyncio

from .. import rule_matchers
from .context import StageContext, StageVerdict


async def judge(ctx: StageContext) -> StageVerdict:
    from .. import intent_triage_engine as engine_mod

    try:
        history_msgs = ctx.history_msgs
        user_msgs = [m for m in history_msgs if m.get("role") == "user"]
        assistant_msgs = [m for m in history_msgs if m.get("role") == "assistant"]
        is_operational_action = bool(engine_mod.OPERATIONAL_ACTION_RE.search(ctx.input_text))
        # 带图轮次不做文本去重(2026-09-10 误退事故):拦截器只比文本,
        # 「坏了」+破损图重发会先于 Step 0.5 图证(OCR 单号/破损定责)被消费
        # 就把会话关成上一轮答复的重放 —— 事故线程重放了修复前(pre-OCR消费)
        # 的旧消歧卡,引导用户挑本店真单对外店单 ORD-77777 误起退款审批。
        # 图证即新证据,与 is_operational_action 同为去重豁免闸。
        carries_image_evidence = bool(ctx.state.get("image_urls"))

        if (
            not is_operational_action
            and not carries_image_evidence
            and len(user_msgs) >= 2
            and assistant_msgs
        ):
            last_user_msg = user_msgs[-2]
            last_assistant_msg = assistant_msgs[-1]

            is_exactly_same = ctx.input_text.strip() == last_user_msg["content"].strip()

            is_semantically_same = False
            if (
                not is_exactly_same
                and len(ctx.input_text.strip()) > 3
                and len(last_user_msg["content"].strip()) > 3
            ):
                from ..semantic_cache import cosine_similarity

                current_vec, last_vec = await asyncio.gather(
                    ctx.ns.SemanticVectorCache.get_embedding_with_cache(ctx.input_text),
                    ctx.ns.SemanticVectorCache.get_embedding_with_cache(last_user_msg["content"]),
                )
                sim = cosine_similarity(current_vec, last_vec)
                # 数字指纹必须一致(2026-09-14):门牌/单号/数量不同的
                # 「相似句」是新请求,严禁重放旧答复
                if sim >= 0.98 and engine_mod._digit_fingerprint(ctx.input_text) == engine_mod._digit_fingerprint(
                    last_user_msg["content"]
                ):
                    is_semantically_same = True

            is_last_response_failed = rule_matchers.is_failed_response(last_assistant_msg["content"])
            has_unsanitized_tags = bool(engine_mod.UNSANITIZED_TAGS_RE.search(last_assistant_msg["content"]))

            if (is_exactly_same or is_semantically_same) and not is_last_response_failed and not has_unsanitized_tags:
                prefix_msg = (
                    "您好！检测到您发送了与刚才相同的咨询。这是刚才为您查询的最新进度：\n\n"
                    if is_exactly_same
                    else "您好！检测到您提问了相似的问题。这是刚才为您查询的最新进度：\n\n"
                )
                reply = f"{prefix_msg}{last_assistant_msg['content']}"
                final_intents = [{"intent": "general_query", "confidence": 1.0}]
                return StageVerdict(
                    terminal=True,
                    result=await ctx.engine.handle_immediate_bypass(
                        ctx.state,
                        "duplicate_bypass",
                        reply,
                        final_intents,
                        "rule",
                        1.0,
                        cards=last_assistant_msg.get("cards"),
                    ),
                )
    except Exception as sh_err:
        print(f"[Triage] 重复提问拦截器异常,已跳过去重检查 (threadId={ctx.thread_id}): {sh_err}")

    return StageVerdict.passthrough()
