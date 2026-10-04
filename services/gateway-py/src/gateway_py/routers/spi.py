"""商户开放 SPI — 镜像 merchant-spi.controller(API-Key 约定式 / HMAC 双通道鉴权)。"""

from __future__ import annotations

import os

from engine_py.approvals import ApprovalGatekeeper
from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel

from .. import conversation_repo, hmac_signer
from ..approval_actions import (
    SPI_ACTIONS,
    build_payload,
    ensure_approval_owned,
    human_reply,
)

router = APIRouter(prefix="/api/v1/spi")

# SPI 静态 API-Key 集:env 优先(SPI_API_KEYS,逗号分隔),缺省回落既有两键保持
# 行为不变 —— 硬编码密钥从源码轮换到部署面的口子(2026-09-26 夜审后项)。
# key_{tenant}/secret_{tenant} 派生形与 HMAC 签名通道不受此集影响。
_VALID_API_KEYS = {
    _k.strip()
    for _k in (os.environ.get("SPI_API_KEYS") or "test_spi_key,master_platform_key").split(",")
    if _k.strip()
}


async def _authenticate(request: Request, api_key: str | None, tenant_id: str) -> None:
    clean_tenant = (tenant_id or "").lower().strip()
    if api_key:
        if api_key in _VALID_API_KEYS or api_key in (f"key_{clean_tenant}", f"secret_{clean_tenant}"):
            return
        # HMAC 通道:signature = HMAC(secret, METHOD\nPATH\nTIMESTAMP\nNONCE\nSHA256(BODY))
        signature = request.headers.get("x-signature")
        timestamp = request.headers.get("x-timestamp")
        nonce = request.headers.get("x-nonce")
        if signature and timestamp and nonce:
            body = (await request.body()).decode(errors="replace")
            if hmac_signer.verify(
                api_key, signature, request.method, request.url.path, timestamp, nonce, body
            ):
                return
    raise HTTPException(401, "Unauthorized SPI access: invalid api key or signature")


def _require_tenant_header(x_tenant_id: str | None) -> str:
    """SPI 租户域路由的租户闸(2026-10-02 code-review:escalation 双路由此前
    无头时以 business_id=None 零过滤读任意租户会话;2026-10-04 架构审查 #2
    扩至审批 resolve 路由 —— 三方通道此前连对象归属校验都没有)。"""
    clean = (x_tenant_id or "").strip().lower()
    if not clean:
        raise HTTPException(400, "x-tenant-id header is required for SPI tenant-scoped routes")
    return clean


@router.post("/approvals/{approval_id}/resolve")
async def spi_resolve_approval(
    approval_id: str,
    body: dict,
    request: Request,
    x_tenant_id: str | None = Header(None),
    x_api_key: str | None = Header(None, alias="x-api-key"),
):
    await _authenticate(request, x_api_key, x_tenant_id or "")
    # 归属闸收口(架构审查 #2):三方通道此前无任何对象归属校验 —— 任何持全局
    # key(test_spi_key/master_platform_key)者可凭猜测的 approvalId 核销任意
    # 租户工单。与 escalation 双路由同闸:租户头必带(400),工单归属他租 403
    # (GateError success 形直穿)。
    tenant = _require_tenant_header(x_tenant_id)
    await ensure_approval_owned(approval_id, tenant, subject="租户")
    # 未知动作诚实 400(与管理台面同口径):此前落引擎按驳回语义静默错误终局。
    action = (str(body.get("action") or "")).strip()
    if action and action not in SPI_ACTIONS:
        raise HTTPException(400, f"未知审批动作: {action}")
    # 核准人契约(admin-readiness 01):SPI 三方通道此前漏注入 resolvedBy/
    # resolvedByRole 且 humanReply 恒 None(`x and None` 恒假)—— 与商户路由
    # 已修的「审批人落库 unknown」同款漂移,在此对齐。角色须用 gatekeeper
    # 白名词表(platform_admin/merchant_operator/system,越界收敛 system):
    # 外部平台审核人按商户操作员声明,未带操作者的自动通道以 AGENT_SPI +
    # system 声明机器身份。装配上收 approval_actions(架构审查 #2)。
    actor = (str(body.get("reviewerId") or body.get("resolvedBy") or "")).strip()
    actor_role = body.get("reviewerRole") or body.get("resolvedByRole")
    if not actor:
        actor = "AGENT_SPI"
        actor_role = actor_role or "system"
    else:
        actor_role = actor_role or "merchant_operator"
    result = await ApprovalGatekeeper.process_approval_action(
        build_payload(
            approval_id=approval_id,
            thread_id=body.get("threadId"),
            action=body.get("action"),
            rejection_reason=body.get("rejectionReason"),
            human_reply_value=human_reply(body.get("humanReply"), body.get("replyMessage")),
            is_finish=body.get("isFinish"),
            resolved_by=actor,
            resolved_by_role=actor_role,
        )
    )
    if result.get("error"):
        raise HTTPException(result.get("statusCode", 400), result["error"])
    return result


class EscalationReplyIn(BaseModel):
    message: str
    operatorId: str | None = None
    operatorName: str | None = None


@router.post("/escalation/{thread_id}/reply")
async def spi_escalation_reply(
    thread_id: str,
    body: EscalationReplyIn,
    request: Request,
    x_tenant_id: str | None = Header(None),
    x_api_key: str | None = Header(None, alias="x-api-key"),
):
    await _authenticate(request, x_api_key, x_tenant_id or "")
    tenant = _require_tenant_header(x_tenant_id)
    timeline = await conversation_repo.get_conversation_timeline(thread_id, tenant)
    if not timeline:
        raise HTTPException(404, f"Conversation '{thread_id}' not found")
    await conversation_repo.append_message(
        {
            "threadId": thread_id,
            "businessId": tenant,
            "role": "assistant",
            "content": body.message,
            "operatorInfo": {"operatorId": body.operatorId, "operatorName": body.operatorName},
        }
    )
    return {"success": True, "delivered": True, "threadId": thread_id}


@router.post("/escalation/{thread_id}/close")
async def spi_escalation_close(
    thread_id: str,
    request: Request,
    x_tenant_id: str | None = Header(None),
    x_api_key: str | None = Header(None, alias="x-api-key"),
):
    await _authenticate(request, x_api_key, x_tenant_id or "")
    tenant = _require_tenant_header(x_tenant_id)
    timeline = await conversation_repo.get_conversation_timeline(thread_id, tenant)
    if not timeline:
        raise HTTPException(404, f"Conversation '{thread_id}' not found")
    await conversation_repo.update_conversation_status(thread_id, tenant, "resolved")
    return {"success": True, "threadId": thread_id, "status": "resolved"}
