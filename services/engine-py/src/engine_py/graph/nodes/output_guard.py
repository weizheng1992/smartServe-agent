"""订单宣称反幻觉硬闸(2026-09-13 用户实报)。

复合流被判单导购终局后,下游 LLM 用叙事宣称「已成功结算下单/订单号
AURORA-ORD-2026-2477」—— 该单号实为上一轮幻觉回复残留在对话历史里的
假单号(幻觉自增殖:上轮幻觉 → 历史 → 本轮引用 → 下轮再引用)。
收口处确定性校验:回复宣称的订单号必须来自本轮 checkoutCart 真实成功
结果;不存在者剥离宣称并替换为诚实说明 —— 幻觉不进对话历史,自增殖链
物理切断。
"""

from __future__ import annotations

import re

from sqlalchemy import text

from ...triage.intent_registry import EXPLICIT_ORDER_ID_RE

# 单号形态单一来源:复用 triage 的显式单号正则(ORD- 任意前缀通用,多租户
# 各品牌单号格式同闸),严禁再硬编码 AURORA 品牌前缀
_CLAIMED_ORDER_ID_RE = EXPLICIT_ORDER_ID_RE
_CHECKOUT_SUCCESS_MARKER = "checkoutcart"
# 叙事宣称词族单一来源:触发(sanitize 的 elif)与剥离(_CLAIM_SENTENCE_RE)
# 共用同一份变体表,严禁触发面窄于剥离面(评审 2026-09-14:「已完成下单结算」
# 在剥离表却不在触发表,宣称漏网)
_NARRATIVE_CLAIM_RE = re.compile(
    r"(?:成功完成结算下单|已完成下单结算|成功下单|完成下单结算|下单结算成功|订单结算成功|结算成功|下单成功)"
)
_CLAIM_SENTENCE_RE = re.compile(
    r"[^。\n]*(?:" + _NARRATIVE_CLAIM_RE.pattern + rf"|订单号[是为:：]?\s*{EXPLICIT_ORDER_ID_RE.pattern})[^。\n]*[。\n]?"
)
# 购物车宣称(2026-09-13 扩展):「已自动将 X 加入购物车」需本轮 cart 技能/
# addToCart 真实成功结果背书 —— 复合流单导购终局下这也是幻觉叙事
_CART_CLAIM_SENTENCE_RE = re.compile(
    r"[^。\n]*(?:已自动将|已成功将|已为您将|已将)[^。\n]*加入(?:您的)?购物车[^。\n]*[。\n]?"
)
_HONEST_NOTICE = "（系统核对：本轮没有产生真实订单，上述下单结算信息无效——商品仍在购物车中，您可以说「结算下单」重新发起。）"
_HONEST_CART_NOTICE = "（系统核对：上述加购未真实发生——如需购买请先让我推荐商品，再说「把第1件加入购物车」。）"


def _real_order_ids(task_plan: dict | None) -> set[str]:
    """本轮工具结果里真实产生的订单号(checkoutCart 成功结果)。"""
    ids: set[str] = set()
    for step in (task_plan or {}).get("subtasks") or []:
        desc = (step.get("description") or "").lower()
        result = step.get("result") or {}
        # 凭据面:checkoutCart 工具 + cart 技能结算分支(CartManageSkill
        # checkout 分支输出真实订单号)都在本轮回执里
        if (
            (_CHECKOUT_SUCCESS_MARKER in desc or "cartskill" in desc)
            and result.get("success")
            and result.get("output")
        ):
            output = result["output"]
            output = output if isinstance(output, str) else json_dumps(output)
            ids.update(_CLAIMED_ORDER_ID_RE.findall(output))
            data = result.get("data") or {}
            order_id = data.get("orderId") if isinstance(data, dict) else None
            if order_id:
                ids.add(str(order_id))
    return ids


def json_dumps(value) -> str:
    import json

    return json.dumps(value, ensure_ascii=False, default=str)


async def sanitize_order_claims(output: str, task_plan: dict | None) -> str:
    """收口校验:宣称的订单号必须与本轮真实 checkout 结果一致。

    - 回复不含订单号宣称 → 原样返回(零开销路径);
    - 宣称 id 全部能在本轮真实结果中找到 → 原样返回;
    - 存在无凭据宣称 → 剥离宣称句并追加诚实说明(幻觉不进历史)。
    """
    if output and _CLAIMED_ORDER_ID_RE.search(output):
        claimed = set(_CLAIMED_ORDER_ID_RE.findall(output))
        real = _real_order_ids(task_plan)
        unbacked = {order_id for order_id in claimed - real if not await _order_exists(order_id)}
        if unbacked:
            output = _strip_claim_sentences(output)
            for order_id in unbacked:
                output = output.replace(order_id, "（无效订单号，已由系统核对移除）")
    elif output and _NARRATIVE_CLAIM_RE.search(output):
        if not _real_order_ids(task_plan):
            output = _strip_claim_sentences(output)
    # 购物车宣称:无本轮真实加购凭据 → 剥离宣称句
    if output and _CART_CLAIM_SENTENCE_RE.search(output) and not _cart_add_backed(task_plan):
        output = _CART_CLAIM_SENTENCE_RE.sub("", output).rstrip()
        if _HONEST_CART_NOTICE not in output:
            output += ("\n\n" if output else "") + _HONEST_CART_NOTICE
    return output


async def _order_exists(order_id: str) -> bool:
    """库中真实存在的订单不算幻觉(历史轮真实下单,本轮引用合法)。"""
    from ...tools_registry import order_domain

    try:
        engine = order_domain._merchant_reader_engine()
        async with engine.connect() as conn:
            row = (
                await conn.execute(
                    text("SELECT 1 FROM merchant_orders WHERE order_id = :o LIMIT 1").bindparams(o=order_id)
                )
            ).scalar()
            return bool(row)
    except Exception as err:
        print(f"[OutputGuard] 订单存在性核验不可达,放行宣称 (orderId={order_id}): {err}")
        return True  # 库不可达时放行(宁可漏拦,不误杀真实订单),但错误必须留痕


def _cart_add_backed(task_plan: dict | None) -> bool:
    """本轮是否存在真实的加购执行(cart 技能/addToCart 成功结果)。"""
    for step in (task_plan or {}).get("subtasks") or []:
        result = step.get("result") or {}
        desc = (step.get("description") or "").lower()
        output = result.get("output") or ""
        output = output if isinstance(output, str) else json_dumps(output)
        if result.get("success") and (
            "cartskill" in desc or "addtocart" in desc or "加入购物车" in output or "已成功将" in output
        ):
            return True
    return False


def _strip_claim_sentences(output: str) -> str:
    cleaned = _CLAIM_SENTENCE_RE.sub("", output)
    if _HONEST_NOTICE not in cleaned:
        cleaned = cleaned.rstrip() + ("\n\n" if cleaned else "") + _HONEST_NOTICE
    return cleaned
