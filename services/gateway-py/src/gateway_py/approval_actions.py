"""审批动作装配 — HITL 动作三通道共享的装配单点(架构审查 #2,2026-10-04)。

同一「审批动作」(approve/reject/release_takeover/human_* → engine
``ApprovalGatekeeper.process_approval_action``)此前有三份并行入口装配:
商户运营台(routers/merchant.admin_approvals_action)、管理台顾客+坐席双面
(routers/admin.resolve_approval)、SPI 三方(routers/spi.spi_resolve_approval)。
actor 派生、对象级租户闸、humanReply 别名解析、operator 快照各抄一份,权限
深度漂移(SPI 通道连归属校验都没有 —— 任何持全局 key 者可核销任意租户工单)。

本 module 收拢**机制**(比较、别名、快照、动作词表、装配),呈现按面适配:

- ``ensure_approval_owned`` / ``ensure_thread_owned``:GateError success 形
  (商户运营台 / SPI 外部通道)。
- ``assert_approval_owned`` / ``assert_thread_owned``:HTTPException detail 形
  (管理台审批面,文案契约钉死)。
- 动作词表(``CUSTOMER_ACTIONS`` 等)是领域词汇唯一权威:管理台面白名单闸
  与 SPI 通道未知动作 400 共用;商户运营台面不做白名单(引擎词表即权威,
  历史口径)。

各面**保留自身**的:身份来源(JWT / 可选 JWT+顾客 / HMAC key)、动作权限画像
(管理台坐席代行须 live_desk:approve;商户运营台本租全权;SPI 凭租户头 +
归属闸)、引擎结果错误映射(包装 success 形 / 裸透传 / raise HTTPException)。
"""

from __future__ import annotations

from engine_py.approvals.gatekeeper import ApprovalGatekeeper, thread_business_id
from fastapi import HTTPException

from .tenant_scope import GateError, same_tenant

# ---------------------------------------------------------------------------
# 动作词表(领域词汇唯一权威;admin.resolve_approval 原地迁移)
# ---------------------------------------------------------------------------
# 顾客自有动作(线程归属绑定:userId 必须是 thread 属主)
CUSTOMER_ACTIONS = frozenset({"approve", "reject", "cancel", "start_human_takeover"})
# 人工坐席动作(必须持员工 JWT);release_takeover 为线程级员工动作(P1)
OPERATOR_ACTIONS = frozenset({"human_message", "human_finish", "release_takeover"})
# 员工代行批驳(资金语义,须 live_desk:approve;P4 台内一等批驳闸)
STAFF_REVIEW_ACTIONS = frozenset({"approve", "reject"})
# SPI 三方通道词表:human_reply 在本面仍合法(P4 退役只收管理台面,SPI 直通
# 引擎白名单,与禁区 useApprovalMachine 的配合挪 P5 一并收口)
SPI_ACTIONS = CUSTOMER_ACTIONS | OPERATOR_ACTIONS | frozenset({"human_reply"})


def human_reply(*values: str | None) -> str | None:
    """humanReply 别名解析单点:显式 humanReply 优先,replyMessage 别名兜底。

    此前三通道各写一遍 ``body.humanReply or body.replyMessage``(SPI 侧曾因
    ``x and None`` 恒假吞掉人工回复)。
    """
    for value in values:
        if value:
            return value
    return None


def operator_snapshot(email: str, display_name: str | None) -> dict:
    """坐席快照(P1 坐席身份):operatorId=email / operatorName=display_name,
    客户端自报不采信。商户运营台与 admin.resolve_approval 曾逐行各抄一份。"""
    return {"operatorId": email, "operatorName": display_name or email}


def actor_from_staff(staff, *, body_actor: str | None = None, body_role: str | None = None,
                     default_role: str = "merchant_operator") -> tuple[str, str]:
    """员工通道核准人派生(admin-readiness 01):缺省取员工 JWT 真身,不再
    兜底自报;角色缺省 merchant_operator(SPI 通道经自有白名词表另行收敛)。"""
    actor = (body_actor or "").strip() or staff.email
    return actor, body_role or default_role


def build_payload(
    *,
    approval_id: str | None,
    thread_id: str | None,
    action: str | None,
    rejection_reason: str | None = None,
    human_reply_value: str | None = None,
    is_finish: bool | None = None,
    resolved_by: str | None = None,
    resolved_by_role: str | None = None,
    operator: dict | None = None,
) -> dict:
    """process_approval_action 引擎载荷的唯一装配点(camelCase 键一次写对)。"""
    payload = {
        "approvalId": approval_id,
        "threadId": thread_id,
        "action": action,
        "rejectionReason": rejection_reason,
        "humanReply": human_reply_value,
        "isFinish": is_finish,
        "resolvedBy": resolved_by,
        "resolvedByRole": resolved_by_role,
    }
    if operator is not None:
        payload["operator"] = operator
    return payload


# ---------------------------------------------------------------------------
# 对象级租户闸 — success 形(GateError;商户运营台 / SPI 外部通道)
# ---------------------------------------------------------------------------
async def ensure_approval_owned(approval_id: str | None, tenant: str, *, subject: str = "员工租户") -> dict | None:
    """审批单归属他租一律 403(fail-open:查无/无属主返回 None 交引擎 404 语义)。"""
    if not approval_id:
        return None
    target = await ApprovalGatekeeper.find_approval_by_id(approval_id)
    target_biz = str((target or {}).get("businessId") or "")
    if target_biz and not same_tenant(target_biz, tenant):
        raise GateError(403, f"审批单不属于{subject} {tenant},拒绝操作")
    return target


async def ensure_thread_owned(thread_id: str | None, tenant: str, *, subject: str = "员工租户") -> None:
    """release_takeover 线程级闸:归属未知(business_id NULL 存量线程)fail-open。"""
    if not thread_id:
        return
    thread_biz = await thread_business_id(thread_id)
    if thread_biz and not same_tenant(thread_biz, tenant):
        raise GateError(403, f"会话不属于{subject} {tenant},拒绝释放")


# ---------------------------------------------------------------------------
# 对象级租户闸 — detail 形(HTTPException;管理台审批面,文案契约钉死)
# ---------------------------------------------------------------------------
async def assert_approval_owned(approval_id: str | None, tenant: str) -> dict | None:
    if not approval_id:
        return None
    target = await ApprovalGatekeeper.find_approval_by_id(approval_id)
    target_biz = str((target or {}).get("businessId") or "")
    if target_biz and not same_tenant(target_biz, tenant):
        raise HTTPException(status_code=403, detail=f"跨租户审批单被拒绝(员工租户 {tenant})")
    return target


async def assert_thread_owned(thread_id: str | None, tenant: str) -> None:
    if not thread_id:
        return
    thread_biz = await thread_business_id(thread_id)
    if thread_biz and not same_tenant(thread_biz, tenant):
        raise HTTPException(status_code=403, detail=f"会话不属于员工租户 {tenant},拒绝释放")
