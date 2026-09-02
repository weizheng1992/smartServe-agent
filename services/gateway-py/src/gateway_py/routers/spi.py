"""商户开放 SPI — 镜像 merchant-spi.controller(API-Key 约定式 / HMAC 双通道鉴权)。"""

from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel

from engine_py.approvals import ApprovalGatekeeper
from .. import conversation_repo
from .. import hmac_signer

router = APIRouter(prefix="/api/v1/spi")

_VALID_API_KEYS = {"test_spi_key", "master_platform_key"}


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


@router.post("/approvals/{approval_id}/resolve")
async def spi_resolve_approval(
    approval_id: str,
    body: dict,
    request: Request,
    x_tenant_id: str | None = Header(None),
    x_api_key: str | None = Header(None, alias="x-api-key"),
):
    await _authenticate(request, x_api_key, x_tenant_id or "")
    result = await ApprovalGatekeeper.process_approval_action(
        {
            "approvalId": approval_id,
            "action": body.get("action"),
            "rejectionReason": body.get("rejectionReason"),
            "humanReply": body.get("reviewerId") and None,
        }
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
    timeline = await conversation_repo.get_conversation_timeline(thread_id, x_tenant_id)
    if not timeline:
        raise HTTPException(404, f"Conversation '{thread_id}' not found")
    await conversation_repo.append_message(
        {
            "threadId": thread_id,
            "businessId": x_tenant_id or timeline["thread"]["businessId"],
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
    timeline = await conversation_repo.get_conversation_timeline(thread_id, x_tenant_id)
    if not timeline:
        raise HTTPException(404, f"Conversation '{thread_id}' not found")
    await conversation_repo.update_conversation_status(thread_id, x_tenant_id or "ecommerce", "resolved")
    return {"success": True, "threadId": thread_id, "status": "resolved"}
