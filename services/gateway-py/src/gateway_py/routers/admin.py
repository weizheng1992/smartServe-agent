"""管理路由组 — tenant / skills / approvals / rag / conversations(镜像同控制器)。"""

from __future__ import annotations

import datetime as _dt
import json
import math

from fastapi import APIRouter, Header, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import desc, select, text

from engine_py.approvals import ApprovalGatekeeper
from engine_py.db import RagDocumentRow, get_session
from engine_py.rag import ContextualRAG
from engine_py.skills import SkillRegistry
from engine_py.tenant_config import get_tenant_config, invalidate_cache, update_tenant_skill_config
from .. import conversation_repo
from ..tenant_context import get_tenant_context

router = APIRouter()


def _require_tenant() -> dict:
    ctx = get_tenant_context()
    if ctx and ctx.get("tenantId"):
        return ctx
    raise HTTPException(403, "Forbidden: tenant context required (x-tenant-id header)")


# ---------------------------------------------------------------------------
# tenant
# ---------------------------------------------------------------------------
@router.get("/api/tenant/ping")
async def tenant_ping(x_tenant_id: str | None = Header(None)):
    ctx = _require_tenant()
    config = await get_tenant_config(ctx["tenantId"])
    return {
        "success": True,
        "message": "Tenant context active",
        "tenant": ctx,
        "config": config,
        "timestamp": _dt.datetime.now().isoformat(),
    }


@router.get("/api/tenant/list")
async def tenant_list():
    try:
        async with get_session() as session:
            rows = (
                (
                    await session.execute(
                        text(
                            "SELECT t.business_id, t.name, t.status, t.industry, t.created_at, tc.spi_config, tc.skills_config "
                            "FROM tenants t LEFT JOIN tenant_configs tc ON LOWER(t.business_id) = LOWER(tc.business_id) "
                            "ORDER BY t.created_at DESC"
                        )
                    )
                )
                .mappings()
                .all()
            )
        if rows:
            tenants = []
            for row in rows:
                spi = row["spi_config"] if isinstance(row["spi_config"], dict) else {}
                skills_cfg = row["skills_config"] if isinstance(row["skills_config"], dict) else {}
                refund_cfg = skills_cfg.get("skill_order_refund")
                refund_limit = (
                    refund_cfg.get("approvalThresholdAmount")
                    if isinstance(refund_cfg, dict) and refund_cfg.get("approvalThresholdAmount") is not None
                    else None
                )
                tenants.append(
                    {
                        "id": row["business_id"],
                        "name": row["name"],
                        "industry": row["industry"] or "综合零售",
                        "channel": "Web + Mobile + SPI",
                        "apiKey": spi.get("apiSecret") or f"key_{row['business_id']}_sec",
                        "refundLimit": refund_limit or 300,
                        "autoEscalation": True,
                        "webhookUrl": spi.get("spiBaseUrl") or "http://localhost:3005",
                        "status": row["status"] or "active",
                        "createdAt": row["created_at"].isoformat().split("T")[0] if row["created_at"] else "2026-01-01",
                    }
                )
            return {"success": True, "tenants": tenants}
        return {"success": True, "tenants": []}
    except Exception as err:  # noqa: BLE001 — 查询失败返回真实空列表，不编造演示数据
        print(f"[TenantService] Failed to query PostgreSQL tenants table: {err}")
        return {"success": True, "tenants": [], "message": "租户注册表暂不可用，请稍后重试"}


class TenantCreateIn(BaseModel):
    id: str
    name: str
    status: str | None = None
    webhookUrl: str | None = None
    apiKey: str | None = None
    refundLimit: int | None = None
    industry: str | None = None
    # 前端 create 以嵌套 config 携带行业/阈值/回调,与平铺字段取并集(平铺优先)
    config: dict | None = None


class TenantUpdateIn(BaseModel):
    name: str
    status: str | None = None
    webhookUrl: str | None = None
    apiKey: str | None = None
    refundLimit: int | None = None
    industry: str | None = None


@router.post("/api/tenant")
async def create_tenant(body: TenantCreateIn):
    clean_id = (body.id or "").lower().strip()
    if not clean_id or not body.name:
        raise HTTPException(400, "Tenant ID and Name are required")

    cfg = body.config or {}
    industry = body.industry or cfg.get("industry")
    webhook_url = body.webhookUrl or cfg.get("webhookUrl")
    refund_limit = body.refundLimit if body.refundLimit is not None else cfg.get("refundLimit")

    spi_config = {
        "mode": "remote_spi",
        "spiBaseUrl": webhook_url or "http://localhost:3005",
        "apiSecret": body.apiKey or f"key_{clean_id}_sec",
        "timeoutMs": 5000,
    }
    skills_config = {"skill_order_refund": {"enabled": True, "approvalThresholdAmount": refund_limit or 300}}

    async with get_session() as session:
        await session.execute(
            text(
                "INSERT INTO tenants (business_id, name, plan_tier, status, industry) "
                "VALUES (:bid, :name, 'enterprise', :status, :industry) "
                "ON CONFLICT (business_id) DO UPDATE SET name = EXCLUDED.name, status = EXCLUDED.status, "
                "industry = COALESCE(EXCLUDED.industry, tenants.industry)"
            ).bindparams(bid=clean_id, name=body.name, status=body.status or "active", industry=industry)
        )
        existing = (
            await session.execute(
                text("SELECT id FROM tenant_configs WHERE LOWER(business_id) = :bid LIMIT 1").bindparams(bid=clean_id)
            )
        ).scalar_one_or_none()
        if existing:
            await session.execute(
                text("UPDATE tenant_configs SET spi_config = :spi, skills_config = :skills, updated_at = NOW() WHERE id = :cid").bindparams(
                    spi=json.dumps(spi_config), skills=json.dumps(skills_config), cid=existing
                )
            )
        else:
            await session.execute(
                text(
                    "INSERT INTO tenant_configs (business_id, system_prompt, welcome_message, status, version, "
                    "spi_config, enabled_skills, skills_config) "
                    "VALUES (:bid, :prompt, :welcome, 'published', 1, CAST(:spi AS jsonb), CAST(:skills_arr AS jsonb), CAST(:skills AS jsonb))"
                ).bindparams(
                    bid=clean_id,
                    prompt=f"You are the official AI Customer Support Agent for {body.name}.",
                    welcome=f"您好！欢迎来到 {body.name}，请问有什么可以帮您？",
                    spi=json.dumps(spi_config),
                    skills_arr=json.dumps(
                        ["skill_order_address_modification", "skill_order_refund", "skill_product_inquiry"]
                    ),
                    skills=json.dumps(skills_config),
                )
            )
        await session.commit()
    invalidate_cache(clean_id)
    return {"success": True, "businessId": clean_id}


@router.put("/api/tenant/{business_id}")
async def update_tenant(business_id: str, body: TenantUpdateIn):
    clean_id = business_id.lower().strip()
    if not body.name:
        raise HTTPException(400, "Tenant Name is required")

    async with get_session() as session:
        existing = (
            await session.execute(
                text("SELECT id FROM tenants WHERE LOWER(business_id) = :bid LIMIT 1").bindparams(bid=clean_id)
            )
        ).scalar_one_or_none()
        if not existing:
            raise HTTPException(404, f"Tenant '{business_id}' not found")

        await session.execute(
            text(
                "UPDATE tenants SET name = :name, status = :status, industry = COALESCE(:industry, industry) "
                "WHERE LOWER(business_id) = :bid"
            ).bindparams(name=body.name, status=body.status or "active", industry=body.industry, bid=clean_id)
        )

        # 合并式覆写 tenant_configs:仅更新请求显式携带的字段,避免整份覆写丢失既有配置
        cfg_row = (
            await session.execute(
                text(
                    "SELECT id, spi_config, skills_config FROM tenant_configs WHERE LOWER(business_id) = :bid LIMIT 1"
                ).bindparams(bid=clean_id)
            )
        ).mappings().first()
        spi = dict(cfg_row["spi_config"]) if isinstance(cfg_row and cfg_row["spi_config"], dict) else {}
        skills = dict(cfg_row["skills_config"]) if isinstance(cfg_row and cfg_row["skills_config"], dict) else {}
        if body.webhookUrl:
            spi["spiBaseUrl"] = body.webhookUrl
        if body.apiKey:
            spi["apiSecret"] = body.apiKey
        spi.setdefault("mode", "remote_spi")
        spi.setdefault("timeoutMs", 5000)
        if body.refundLimit is not None:
            refund_cfg = skills.get("skill_order_refund")
            refund_cfg = dict(refund_cfg) if isinstance(refund_cfg, dict) else {}
            refund_cfg["enabled"] = refund_cfg.get("enabled", True)
            refund_cfg["approvalThresholdAmount"] = body.refundLimit
            skills["skill_order_refund"] = refund_cfg

        if cfg_row:
            await session.execute(
                text(
                    "UPDATE tenant_configs SET spi_config = CAST(:spi AS jsonb), skills_config = CAST(:skills AS jsonb), "
                    "updated_at = NOW() WHERE id = :cid"
                ).bindparams(spi=json.dumps(spi), skills=json.dumps(skills), cid=cfg_row["id"])
            )
        else:
            await session.execute(
                text(
                    "INSERT INTO tenant_configs (business_id, system_prompt, welcome_message, status, version, "
                    "spi_config, enabled_skills, skills_config) "
                    "VALUES (:bid, :prompt, :welcome, 'published', 1, CAST(:spi AS jsonb), CAST(:skills_arr AS jsonb), CAST(:skills AS jsonb))"
                ).bindparams(
                    bid=clean_id,
                    prompt=f"You are the official AI Customer Support Agent for {body.name}.",
                    welcome=f"您好！欢迎来到 {body.name}，请问有什么可以帮您？",
                    spi=json.dumps(spi),
                    skills_arr=json.dumps(
                        ["skill_order_address_modification", "skill_order_refund", "skill_product_inquiry"]
                    ),
                    skills=json.dumps(skills),
                )
            )
        await session.commit()
    invalidate_cache(clean_id)
    return {"success": True, "businessId": clean_id}


@router.delete("/api/tenant/{business_id}")
async def delete_tenant(business_id: str):
    clean_id = business_id.lower().strip()
    async with get_session() as session:
        await session.execute(
            text("DELETE FROM tenant_configs WHERE LOWER(business_id) = :bid").bindparams(bid=clean_id)
        )
        await session.execute(text("DELETE FROM tenants WHERE LOWER(business_id) = :bid").bindparams(bid=clean_id))
        await session.commit()
    invalidate_cache(clean_id)
    return {"success": True}


# ---------------------------------------------------------------------------
# skills
# ---------------------------------------------------------------------------
@router.get("/api/skills/registry")
async def skills_registry():
    return {"success": True, "skills": [s.metadata for s in SkillRegistry.get_all_skills()]}


@router.get("/api/skills/config")
async def skills_config(x_tenant_id: str | None = Header(None)):
    ctx = _require_tenant()
    skills = await _tenant_skills(ctx["tenantId"])
    return {"success": True, "tenantId": ctx["tenantId"], "skills": skills}


async def _tenant_skills(tenant_id: str) -> list[dict]:
    config = await get_tenant_config(tenant_id)
    skills_config = config.get("skillsConfig") or {}
    enabled_skills = config.get("enabledSkills")
    result = []
    for skill in SkillRegistry.get_all_skills():
        tenant_skill = skills_config.get(skill.metadata["id"])
        is_enabled = (
            tenant_skill.get("enabled")
            if isinstance(tenant_skill, dict) and tenant_skill.get("enabled") is not None
            else (not enabled_skills or skill.metadata["id"] in enabled_skills)
        )
        threshold = (
            tenant_skill.get("approvalThresholdAmount")
            if isinstance(tenant_skill, dict) and tenant_skill.get("approvalThresholdAmount") is not None
            else skill.metadata.get("approvalThresholdAmount", 50)
        )
        result.append(
            {
                **skill.metadata,
                "enabled": is_enabled,
                "effectiveApprovalThreshold": threshold,
                "customPolicyPrompt": (tenant_skill or {}).get("customPolicyPrompt"),
            }
        )
    return result


@router.put("/api/skills/config")
async def update_skills_config(body: dict, x_tenant_id: str | None = Header(None)):
    ctx = _require_tenant()
    if body.get("skillId"):
        updated = await update_tenant_skill_config(ctx["tenantId"], body["skillId"], body)
        return {
            "success": True,
            "tenantId": ctx["tenantId"],
            "skillId": body["skillId"],
            "config": (updated.get("skillsConfig") or {}).get(body["skillId"]),
        }
    skills = await _tenant_skills(ctx["tenantId"])
    return {"success": True, "tenantId": ctx["tenantId"], "skills": skills}


@router.get("/api/skills/tenant")
async def skills_tenant_alias(x_tenant_id: str | None = Header(None)):
    ctx = _require_tenant()
    skills = await _tenant_skills(ctx["tenantId"])
    return {"success": True, "tenantId": ctx["tenantId"], "skills": skills}


@router.patch("/api/skills/tenant/{skill_id}")
async def update_tenant_skill(skill_id: str, body: dict, x_tenant_id: str | None = Header(None)):
    ctx = _require_tenant()
    updated = await update_tenant_skill_config(ctx["tenantId"], skill_id, body)
    return {
        "success": True,
        "tenantId": ctx["tenantId"],
        "skillId": skill_id,
        "config": (updated.get("skillsConfig") or {}).get(skill_id),
    }


# ---------------------------------------------------------------------------
# approvals(双前缀)
# ---------------------------------------------------------------------------
approvals_router = APIRouter()


@approvals_router.get("/api/approvals")
@approvals_router.get("/api/chat/approvals")
async def list_approvals(
    request: Request,
    tenantId: str | None = Query(None),
    businessId: str | None = Query(None),
    status: str | None = Query(None),
    actionType: str | None = Query(None),
):
    ctx = get_tenant_context()
    effective_tenant = tenantId or businessId or (ctx or {}).get("tenantId")
    try:
        approvals = await ApprovalGatekeeper.list_pending_approvals(
            {"tenantId": effective_tenant, "status": status, "actionType": actionType}
        )
    except Exception as err:  # noqa: BLE001
        print(f"[ApprovalsService] Failed to list approvals: {err}")
        approvals = []
    return {"success": True, "approvals": approvals, "total": len(approvals), "tenantId": effective_tenant}


@approvals_router.post("/api/approvals")
async def resolve_approval(body: dict, request: Request):
    ctx = get_tenant_context()
    options = {
        "approvalId": body.get("approvalId"),
        "threadId": body.get("threadId"),
        "action": body.get("action"),
        "rejectionReason": body.get("rejectionReason"),
        "humanReply": body.get("humanReply") or body.get("replyMessage"),
        "isFinish": body.get("isFinish"),
    }
    return await ApprovalGatekeeper.process_approval_action(options)


# ---------------------------------------------------------------------------
# rag
# ---------------------------------------------------------------------------
@router.get("/api/rag/documents")
async def rag_documents(tenantId: str | None = Query(None), x_tenant_id: str | None = Header(None)):
    tenant_id = tenantId or x_tenant_id
    async with get_session() as session:
        stmt = select(RagDocumentRow).order_by(desc(RagDocumentRow.created_at))
        if tenant_id and tenant_id != "all":
            stmt = stmt.where(RagDocumentRow.business_id == tenant_id)
        rows = (await session.execute(stmt)).scalars().all()
    data = [_rag_item(r) for r in rows]
    return {"success": True, "tenantId": tenant_id or "all", "total": len(data), "data": data}


def _rag_item(r: RagDocumentRow) -> dict:
    meta = r.metadata_ if isinstance(r.metadata_, dict) else {}
    doc_title = (
        meta.get("title")
        or meta.get("docTitle")
        or r.source_url
        or (
            "Nike 官方售后与质保政策"
            if r.business_id == "nike"
            else "Adidas 品牌服务与退换细则"
            if r.business_id == "adidas"
            else "官方通用商城知识文档"
        )
    )
    category = meta.get("category") or ("售后政策" if r.business_id == "nike" else "商品知识")
    created = _dt.date.today().isoformat() if not r.created_at else r.created_at.isoformat().split("T")[0]
    return {
        "id": str(r.id),
        "businessId": r.business_id,
        "docTitle": doc_title,
        "title": doc_title,
        "category": category,
        "content": r.chunk_text,
        "chunkText": r.chunk_text,
        "tokenCount": math.ceil(len(r.chunk_text or "") * 1.3),
        "sourceUrl": r.source_url or None,
        "contextualSummary": r.contextual_summary or None,
        "metadata": meta,
        "createdAt": created,
        "updatedAt": created,
    }


class RagDocIn(BaseModel):
    chunkText: str
    businessId: str | None = None
    sourceUrl: str | None = None
    contextualSummary: str | None = None
    metadata: dict | None = None


@router.post("/api/rag/documents", status_code=201)
async def add_rag_document(body: RagDocIn, x_tenant_id: str | None = Header(None)):
    business_id = body.businessId or x_tenant_id or "ecommerce"
    meta = {**(body.metadata or {}), "title": "知识文档", "category": "通用政策"}
    async with get_session() as session:
        row = RagDocumentRow(
            business_id=business_id,
            source_url=body.sourceUrl,
            chunk_text=body.chunkText,
            contextual_summary=body.contextualSummary or body.chunkText[:50],
            metadata=meta,
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)
    return {"success": True, "data": _rag_item(row)}


@router.delete("/api/rag/documents/{doc_id}")
async def delete_rag_document(doc_id: str, tenantId: str | None = Query(None), x_tenant_id: str | None = Header(None)):
    tenant_id = tenantId or x_tenant_id
    async with get_session() as session:
        stmt = select(RagDocumentRow).where(RagDocumentRow.id == doc_id)
        if tenant_id and tenant_id != "all":
            stmt = stmt.where(RagDocumentRow.business_id == tenant_id)
        row = (await session.execute(stmt)).scalar_one_or_none()
        if not row:
            raise HTTPException(404, f"Document with ID '{doc_id}' not found in database")
        await session.delete(row)
        await session.commit()
    return {"success": True, "message": f"Document {doc_id} deleted successfully"}


class RagQueryIn(BaseModel):
    query: str
    tenantId: str | None = None


@router.post("/api/rag/query")
async def rag_query(body: RagQueryIn, x_tenant_id: str | None = Header(None)):
    tenant_id = body.tenantId or x_tenant_id
    biz_id = tenant_id if tenant_id and tenant_id != "all" else "ecommerce"
    rag = ContextualRAG(biz_id)
    results = await rag.search_relevant_docs(body.query, 5)
    if results:
        return {
            "success": True,
            "data": {
                "query": body.query,
                "tenantId": biz_id,
                "matches": [
                    {
                        "id": r["id"],
                        "businessId": r["businessId"],
                        "chunkText": r["chunkText"],
                        "contextualSummary": r["contextualSummary"],
                        "score": r["similarity"],
                    }
                    for r in results
                ],
            },
        }
    docs = await rag_documents(tenantId, x_tenant_id)
    return {
        "success": True,
        "data": {
            "query": body.query,
            "tenantId": tenant_id or "all",
            "matches": [
                {
                    "id": d["id"],
                    "businessId": d["businessId"],
                    "chunkText": d["chunkText"],
                    "contextualSummary": d["contextualSummary"],
                    "score": 0.75,
                }
                for d in docs["data"][:3]
            ],
        },
    }


# ---------------------------------------------------------------------------
# conversations
# ---------------------------------------------------------------------------
@router.get("/api/conversations")
async def list_conversations(
    status: str | None = Query(None),
    tag: str | None = Query(None),
    search: str | None = Query(None),
    limit: str | None = Query(None),
    offset: str | None = Query(None),
    request: Request = None,
):
    ctx = get_tenant_context()
    tenant_id = (
        request.headers.get("x-tenant-id")
        or request.headers.get("x-business-id")
        or request.query_params.get("tenantId")
        or request.query_params.get("businessId")
        or "ecommerce"
    ) if request else ((ctx or {}).get("tenantId") or "ecommerce")

    result = await conversation_repo.list_conversations(
        business_id=tenant_id,
        status=None if status == "all" else status,
        tag=tag,
        search_keyword=search,
        limit=int(limit) if limit else 20,
        offset=int(offset) if offset else 0,
    )
    return {"success": True, "tenantId": tenant_id, "conversations": result["items"], "total": result["total"]}


@router.get("/api/conversations/{thread_id}")
async def get_conversation(thread_id: str, request: Request):
    tenant_id = (
        request.headers.get("x-tenant-id")
        or request.headers.get("x-business-id")
        or request.query_params.get("tenantId")
        or request.query_params.get("businessId")
    )
    timeline = await conversation_repo.get_conversation_timeline(thread_id, tenant_id)
    return {"success": True, "data": timeline}


class ConversationStatusIn(BaseModel):
    status: str
    assignedOperatorId: str | None = None
    tags: list[str] | None = None


@router.post("/api/conversations/{thread_id}/status")
async def update_conversation_status(thread_id: str, body: ConversationStatusIn, request: Request):
    tenant_id = request.headers.get("x-tenant-id") or request.headers.get("x-business-id") or "ecommerce"
    updated = await conversation_repo.update_conversation_status(
        thread_id, tenant_id, body.status, body.assignedOperatorId, body.tags
    )
    if not updated:
        raise HTTPException(404, f"Conversation '{thread_id}' not found")
    return {"success": True, "data": updated}
