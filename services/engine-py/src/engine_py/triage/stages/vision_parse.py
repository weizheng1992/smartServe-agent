"""📷 Step 0.5 多模态视觉解析 — Stage(原 process 段,逐字搬移)。

带图轮次调用视觉分析(OCR 单号/快递面单/破损评级),产出 vision_analysis
与 damage_assessment 供后续消歧阶段消费;图内 OCR 单号提取为 vision_order_id。
分析失败降级启发式兜底,不炸会话。
"""

from __future__ import annotations

from ...event_bus import emit_status
from .context import StageContext, StageVerdict


async def judge(ctx: StageContext) -> StageVerdict:
    damage_assessment = ctx.state.get("damage_assessment")
    vision_analysis: dict | None = None  # Step 1.6 商品归属消歧消费(摘要/物体)
    if ctx.state.get("image_urls"):
        if ctx.state.get("job_id"):
            await emit_status(
                ctx.state["job_id"],
                "📷 多模态感知：正在进行图像 OCR、快递面单解析与商品破损瑕疵评级...",
                node="triage",
            )
        try:
            vision_analysis = await ctx.ns.analyze_images(ctx.state["image_urls"], ctx.input_text)
            damage_assessment = vision_analysis.get("damageAssessment") or damage_assessment
        except Exception as vision_err:
            print(f"[Triage] 多模态视觉解析失败,降级启发式兜底 (threadId={ctx.thread_id}): {vision_err}")

    # 图内 OCR 单号(2026-09-09):消费语义与文本单号一致 —— 进实体/订单上下文,
    # 查无此单由技能归属校验诚实报错;此前算完即丢,图内明示单号对流程零贡献
    vision_order_id = str((vision_analysis or {}).get("extractedOrderId") or "").strip().upper() or None

    ctx.damage_assessment = damage_assessment
    ctx.vision_analysis = vision_analysis
    ctx.vision_order_id = vision_order_id
    return StageVerdict.passthrough()
