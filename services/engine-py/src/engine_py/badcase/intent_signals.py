"""意图信号检测 — 分类器冲突 / 宣称与落库不符(intent-arbitration 02,2026-09-10)。

两个新信号源接入候选池,数据源是 01 的仲裁留痕(intent_logs.candidates)
与会话终稿:
- ``intent_conflict``:同一输入的仲裁候选中,不同判定层给出了跨意图族的
  不同判定(动作形 × 咨询/兜底形)——「退货政策」被槽位层判退款而分类器
  判咨询一类,正是 07 冲突触发仲裁要治的靶场景;
- ``claim_mismatch``:终稿宣称已退款/已提交审批,但审批表对整个会话无
  任何记录 —— ORD-77777 编造审批一类的结构性兜底:幽灵单前置拦截挡住了
  开 HITL 工单,但 finish 终稿幻觉出的「已为您发起退款」宣称也要能被捕到。

检测只读仲裁留痕与审批表;入池走 ``record_badcase_signal`` 静默降级,
绝不阻断主链路(观测性规范)。仓库零原始数据:note 只存层名/意图名与
命中模式,不存对话原文。
"""

from __future__ import annotations

import re

from sqlalchemy import func, select

from ..db import PendingApproval, Thread, get_session
from ..triage.intent_registry import CONSULT_SIDE_INTENTS
from .pool import SOURCE_CLAIM_MISMATCH, SOURCE_INTENT_CONFLICT, record_badcase_signal

# 咨询/兜底形意图族:不触发执行管道的类目。槽位层的 chat、快轨的 consult、
# 兜底 general_query、范畴外 out_of_scope 同族;其余(refund/order_return/
# cart_*/skill_* 等)一律视为动作形 —— 与 07 冲突检测保持同一口径。
# 集合本体上移 intent_registry(工单04 2026-09-11),triage Step3 consult
# 降级与本检测共用同一口径;此处别名保持本模块既有引用不动。
_CONSULT_SIDE_INTENTS = CONSULT_SIDE_INTENTS

# 终稿宣称模式:宣称已发起退款/退货/审批动作。均要求「已/已经」先行,
# 「尚未/未」类否定措辞天然不命中。
_CLAIM_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(已|已经).{0,6}(发起|提交|办理|完成|成功|执行|通过).{0,6}(退款|退货|审批|工单|申请)"),
    re.compile(r"(退款|退货|审批|工单|申请).{0,4}(已|已经).{0,2}(成功|完成|通过|受理|提交)"),
    re.compile(r"已为您.{0,12}(退款|退货|发起退款|提交)"),
)


def detect_intent_conflict(candidates: list[dict] | None) -> dict | None:
    """跨意图族冲突检测:不同判定层 × 动作形对咨询形。

    Returns: 冲突摘要 ``{"a": {...}, "b": {...}}``(两提议的层/意图/置信,
    不含输入原文);无冲突返回 None。同层内部多判定(判定1 的双 embedding
    提议)与同族异意(general_query vs out_of_scope)不算冲突。
    """
    if not candidates:
        return None
    for i, a in enumerate(candidates):
        for b in candidates[i + 1 :]:
            if a.get("layer") == b.get("layer"):
                continue
            ia, ib = a.get("intent"), b.get("intent")
            if not ia or not ib or ia == ib:
                continue
            a_side, b_side = ia in _CONSULT_SIDE_INTENTS, ib in _CONSULT_SIDE_INTENTS
            if a_side != b_side:
                return {"a": dict(a), "b": dict(b)}
    return None


async def _tenant_of_thread(thread_id: str | None) -> str:
    """thread → business_id(租户边界);查不到回退默认租户。"""
    if not thread_id:
        return "ecommerce"
    async with get_session() as session:
        row = (
            await session.execute(select(Thread.business_id).where(Thread.id == thread_id).limit(1))
        ).scalar_one_or_none()
        return row or "ecommerce"


async def record_intent_conflict_if_any(thread_id: str | None, candidates: list[dict] | None) -> None:
    """挂 ``log_intent_to_db`` 落库成功后:候选跨意图族 → 入池(先验 neutral,
    冲突可能是快轨合法压制,人审定性)。同会话 dedupe,直至 triage 出池。"""
    conflict = detect_intent_conflict(candidates)
    if conflict is None or not thread_id:
        return
    await record_badcase_signal(
        SOURCE_INTENT_CONFLICT,
        conversation_ref=f"thread:{thread_id}",
        business_id=await _tenant_of_thread(thread_id),
        dedupe=True,
        note=(
            f"跨意图族冲突: {conflict['a']['layer']}={conflict['a']['intent']}@{conflict['a']['confidence']}"
            f" vs {conflict['b']['layer']}={conflict['b']['intent']}@{conflict['b']['confidence']}"
        ),
    )


def detect_claim(text: str) -> str | None:
    """终稿宣称检测:命中返回首个匹配片段(入池 note 溯源),未命中返回 None。"""
    for pattern in _CLAIM_PATTERNS:
        m = pattern.search(text or "")
        if m:
            return m.group(0)
    return None


async def record_claim_mismatch_if_any(thread_id: str | None, business_id: str, output_text: str) -> None:
    """挂 run_agent 会话收口处:宣称退款/审批动作 × 审批表整会话零记录 → 入池。

    审批表有记录则宣称大概率有据(精确对账需关联动作语义,v1 只捕零记录的
    裸幻觉;先验 suspected_defect —— 无中生有的宣称几乎必是缺陷)。
    """
    claim = detect_claim(output_text)
    if claim is None or not thread_id:
        return
    async with get_session() as session:
        approvals = (
            await session.execute(
                select(func.count()).select_from(PendingApproval).where(PendingApproval.thread_id == thread_id)
            )
        ).scalar_one()
    if approvals > 0:
        return
    await record_badcase_signal(
        SOURCE_CLAIM_MISMATCH,
        conversation_ref=f"thread:{thread_id}",
        business_id=business_id or await _tenant_of_thread(thread_id),
        dedupe=True,
        note=f"终稿宣称[{claim}]但审批表无任何记录",
    )
