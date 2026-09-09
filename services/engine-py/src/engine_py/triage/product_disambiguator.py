"""破损图 → 商品归属消歧(2026-09-09)。

场景:用户上传商品破损照片,图内无面单/订单号(OCR 通道失效)。思路是
"图 + 账户数据"而非硬认图:vision 摘要 × 用户近单商品行 → 一次普通
LLM 调用消歧 → 唯一高置信命中注入 ``order_context.targetOrderId``
(退款技能严格抽取器只认当前输入正则与该键,slot_extractor.py:72-82);
多候选/低置信/失败则交由调用方出商品选择卡片问用户。任何失败绝不
炸会话主链路 —— 最坏多问一次(与 vision 同哲学)。

设计共识(grilling 2026-09-09):
- 触发 = 带图 + 售后意图(order_return/refund)+ 无 targetOrderId
- 自动注入阈值 confidence ≥ 0.8,且 order_id 必须在候选集内(防幻觉)
- 匹配粒度 = 商品名级(订单链路无 skuCode/spuId 独立字段,事实如此)
- 候选池 = 最近 MAX_CANDIDATE_ORDERS 单的商品行拍平,数据优先级与
  订单列表同源:商户真单(agent_merchant)优先,engine 本地表兜底
"""

from __future__ import annotations

from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field

from ..llm.chat import get_chat_model
from ..tools_registry.order_domain import OrderDomainService
from .slot_extractor import AgentIntentType

# 售后索赔类意图(直引 slot_extractor 常量,防手抄漂移)
AFTER_SALE_INTENTS = {AgentIntentType.ORDER_RETURN, AgentIntentType.REFUND}
# 唯一命中自动注入的置信阈值;低于此值一律出选择卡片
CONFIDENCE_AUTO_INJECT = 0.8
MAX_CANDIDATE_ORDERS = 5
# 选择卡片选项上限(候选池拍平后可能较多,截断防卡片爆长)
MAX_CARD_OPTIONS = 8


class ProductMatch(BaseModel):
    """消歧结构化输出 schema(工具取参 snake,出参转 camel 契约字典)。"""

    order_id: str | None = Field(None, description="最匹配的订单号,必须原样取自候选列表")
    product_name: str | None = Field(None, description="最匹配的商品名,必须原样取自候选列表")
    confidence: float = Field(0.0, ge=0.0, le=1.0, description="匹配置信度;都不像则给低值")


_PROMPT_TEMPLATE = """你是电商客服平台的商品归属判定助手。
用户上传了一张商品破损照片,视觉模块已产出图片摘要。请根据摘要判断破损的是用户近期订单中的哪件商品。

图片视觉摘要:{visual_summary}
检测到的物体:{detected_objects}

用户近期订单商品候选(编号、订单号、商品名):
{candidates}

判定规则:
1. 选择与图片摘要最匹配的一个候选,order_id/product_name 必须原样取自上表;
2. confidence 表示把握:品类+特征(颜色/款式)都能对上给 0.8 以上;仅品类相似给 0.4~0.7;都对不上给 0.2 以下;
3. 不允许编造候选列表之外的订单号或商品名。"""


async def disambiguate_product(
    vision_analysis: dict | None,
    user_id: str | None,
    business_id: str | None,
    *,
    model=None,
) -> dict:
    """视觉摘要 × 近单商品行消歧。

    返回(始终可序列化,不抛出):
    - {"status": "no_orders", "candidates": []}          用户无候选订单
    - {"status": "matched", "orderId", "productName",
       "confidence", "candidates"}                        唯一高置信命中
    - {"status": "ambiguous", "candidates": [...]}       多候选/低置信/模型失败/疑似幻觉
    """
    candidates = await _build_candidates_async(user_id, business_id)
    if not candidates:
        return {"status": "no_orders", "candidates": []}

    visual_summary = (vision_analysis or {}).get("visualSummary") or ""
    detected = (vision_analysis or {}).get("detectedObjects") or []
    if not visual_summary and not detected:
        return {"status": "ambiguous", "candidates": candidates}

    try:
        chat = model or get_chat_model()
        structured = chat.with_structured_output(ProductMatch, method="function_calling")
        lines = [
            f"{i + 1}. 订单 {c['orderId']}:{c['productName']} ×{c['quantity']}"
            for i, c in enumerate(candidates)
        ]
        prompt = _PROMPT_TEMPLATE.format(
            visual_summary=visual_summary or "(无摘要)",
            detected_objects=", ".join(str(d) for d in detected) or "(无)",
            candidates="\n".join(lines),
        )
        parsed = await structured.ainvoke([HumanMessage(content=prompt)])
    except Exception as err:
        print(f"[ProductDisambiguator] LLM 消歧失败,降级出选择卡片: {err}")
        return {"status": "ambiguous", "candidates": candidates}

    candidate_keys = {(c["orderId"], c["productName"]) for c in candidates}
    matched_order = (parsed.order_id or "").strip()
    matched_product = (parsed.product_name or "").strip()
    confidence = float(parsed.confidence or 0.0)

    # 防幻觉:命中项必须原样存在于候选集;否则视同未命中
    if (
        confidence >= CONFIDENCE_AUTO_INJECT
        and (matched_order, matched_product) in candidate_keys
    ):
        return {
            "status": "matched",
            "orderId": matched_order,
            "productName": matched_product,
            "confidence": confidence,
            "candidates": candidates,
        }
    return {"status": "ambiguous", "candidates": candidates}


async def _build_candidates_async(user_id: str | None, business_id: str | None) -> list[dict]:
    """候选池构建:近单商品行走 OrderDomainService.get_recent_product_lines
    (商户真单优先/引擎本地表兜底,两库优先级与订单列表同源);失败返回空列表,不抛出。"""
    try:
        return await OrderDomainService.get_recent_product_lines(
            user_id, business_id, limit=MAX_CANDIDATE_ORDERS
        )
    except Exception as err:
        print(f"[ProductDisambiguator] 候选订单查询失败: {err}")
        return []


def build_select_card(candidates: list[dict]) -> dict:
    """多候选 → 商品选择 quick_replies 卡片(复用冻结契约,零新增类型)。

    点选动作走 send_message:文本携带订单号,下一轮经 triage 的
    extract_explicit_order_id 正则通道注入 targetOrderId,天然闭环;
    不做直达退款(用户点选只表明"是这件",流程仍交意图判断)。
    """
    options = []
    for c in candidates[:MAX_CARD_OPTIONS]:
        label = f"{c['productName']}（订单 {c['orderId']}）"
        options.append(
            {
                "label": label,
                "action": "send_message",
                "payload": {"text": f"我反馈的是订单 {c['orderId']} 的 {c['productName']} 出现破损问题"},
            }
        )
    return {"type": "quick_replies", "data": {"title": "请问破损的是哪件商品？", "options": options}}
