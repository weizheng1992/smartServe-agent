"""管理路由组 — tenant / skills / approvals / rag / conversations(镜像同控制器)。"""

from __future__ import annotations

import datetime as _dt
import json
import math

from engine_py.approvals import ApprovalGatekeeper
from engine_py.db import RagDocumentRow, get_session
from engine_py.onboarding import validate_onboarding_config
from engine_py.rag import ContextualRAG
from engine_py.skills import SkillRegistry
from engine_py.tenant_config import get_tenant_config, invalidate_cache, update_tenant_skill_config
from fastapi import APIRouter, Header, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import desc, select, text

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
                            "SELECT t.business_id, t.name, t.status, t.industry, t.created_at, tc.spi_config, tc.skills_config, tc.onboarding_config "
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
                        # 编辑面回读(new-user-onboarding E):无配置租户回 None,
                        # 前端 JSON 文本域以「未配置」态呈现而非伪造默认值
                        "onboardingConfig": (
                            row["onboarding_config"] if isinstance(row["onboarding_config"], dict) else None
                        ),
                    }
                )
            return {"success": True, "tenants": tenants}
        return {"success": True, "tenants": []}
    except Exception as err:
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
    # 新用户引导配置(2026-09-10 补齐「仅编辑态」边界):与 PUT 同语义 ——
    # 服务端 schema 校验,携带即写入(新建即生效,不必先建再编辑)
    onboardingConfig: dict | None = None


class TenantUpdateIn(BaseModel):
    name: str
    status: str | None = None
    webhookUrl: str | None = None
    apiKey: str | None = None
    refundLimit: int | None = None
    industry: str | None = None
    # 新用户引导配置(new-user-onboarding E):完整 JSON 文档,提供即整体覆写
    # (部分字段回落是 resolve_onboarding_config 读取侧的职责),服务端 schema 校验
    onboardingConfig: dict | None = None


@router.post("/api/tenant")
async def create_tenant(body: TenantCreateIn):
    clean_id = (body.id or "").lower().strip()
    if not clean_id or not body.name:
        raise HTTPException(400, "Tenant ID and Name are required")

    cfg = body.config or {}
    industry = body.industry or cfg.get("industry")
    webhook_url = body.webhookUrl or cfg.get("webhookUrl")
    refund_limit = body.refundLimit if body.refundLimit is not None else cfg.get("refundLimit")

    # 与 PUT 同语义的服务端 schema 校验:JSON 手编错形诚实失败(400),
    # 而非落库后在首访欢迎/引擎旁路两处静默回落平台默认
    if body.onboardingConfig is not None:
        onboarding_errors = validate_onboarding_config(body.onboardingConfig)
        if onboarding_errors:
            raise HTTPException(400, f"onboardingConfig 校验失败: {'; '.join(onboarding_errors)}")

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
            # 合并式:仅当请求携带 onboardingConfig 时写入(重建既有租户未携带 → 不动既有引导配置)
            if body.onboardingConfig is not None:
                await session.execute(
                    text(
                        "UPDATE tenant_configs SET spi_config = :spi, skills_config = :skills, "
                        "onboarding_config = CAST(:onboarding AS jsonb), updated_at = NOW() WHERE id = :cid"
                    ).bindparams(
                        spi=json.dumps(spi_config),
                        skills=json.dumps(skills_config),
                        onboarding=json.dumps(body.onboardingConfig),
                        cid=existing,
                    )
                )
            else:
                await session.execute(
                    text("UPDATE tenant_configs SET spi_config = :spi, skills_config = :skills, updated_at = NOW() WHERE id = :cid").bindparams(
                        spi=json.dumps(spi_config), skills=json.dumps(skills_config), cid=existing
                    )
                )
        else:
            await session.execute(
                text(
                    "INSERT INTO tenant_configs (business_id, system_prompt, welcome_message, status, version, "
                    "spi_config, enabled_skills, skills_config, onboarding_config) "
                    "VALUES (:bid, :prompt, :welcome, 'published', 1, CAST(:spi AS jsonb), CAST(:skills_arr AS jsonb), "
                    "CAST(:skills AS jsonb), CAST(:onboarding AS jsonb))"
                ).bindparams(
                    bid=clean_id,
                    prompt=f"You are the official AI Customer Support Agent for {body.name}.",
                    welcome=f"您好！欢迎来到 {body.name}，请问有什么可以帮您？",
                    spi=json.dumps(spi_config),
                    skills_arr=json.dumps(
                        ["skill_order_address_modification", "skill_order_refund", "skill_product_inquiry"]
                    ),
                    skills=json.dumps(skills_config),
                    onboarding=json.dumps(body.onboardingConfig) if body.onboardingConfig is not None else None,
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

    # 服务端 schema 校验(new-user-onboarding E):JSON 手编错形必须诚实失败,
    # 而非落库后在首访欢迎/引擎旁路两处静默回落平台默认
    if body.onboardingConfig is not None:
        onboarding_errors = validate_onboarding_config(body.onboardingConfig)
        if onboarding_errors:
            raise HTTPException(400, f"onboardingConfig 校验失败: {'; '.join(onboarding_errors)}")

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
                    "SELECT id, spi_config, skills_config, onboarding_config FROM tenant_configs "
                    "WHERE LOWER(business_id) = :bid LIMIT 1"
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
        # onboarding_config:请求携带即整体覆写(完整 schema 文档),未携带保留既有
        onboarding = (
            dict(body.onboardingConfig)
            if body.onboardingConfig is not None
            else (dict(cfg_row["onboarding_config"]) if isinstance(cfg_row and cfg_row["onboarding_config"], dict) else None)
        )

        if cfg_row:
            await session.execute(
                text(
                    "UPDATE tenant_configs SET spi_config = CAST(:spi AS jsonb), skills_config = CAST(:skills AS jsonb), "
                    "onboarding_config = CAST(:onboarding AS jsonb), updated_at = NOW() WHERE id = :cid"
                ).bindparams(
                    spi=json.dumps(spi),
                    skills=json.dumps(skills),
                    onboarding=json.dumps(onboarding) if onboarding is not None else None,
                    cid=cfg_row["id"],
                )
            )
        else:
            await session.execute(
                text(
                    "INSERT INTO tenant_configs (business_id, system_prompt, welcome_message, status, version, "
                    "spi_config, enabled_skills, skills_config, onboarding_config) "
                    "VALUES (:bid, :prompt, :welcome, 'published', 1, CAST(:spi AS jsonb), CAST(:skills_arr AS jsonb), "
                    "CAST(:skills AS jsonb), CAST(:onboarding AS jsonb))"
                ).bindparams(
                    bid=clean_id,
                    prompt=f"You are the official AI Customer Support Agent for {body.name}.",
                    welcome=f"您好！欢迎来到 {body.name}，请问有什么可以帮您？",
                    spi=json.dumps(spi),
                    skills_arr=json.dumps(
                        ["skill_order_address_modification", "skill_order_refund", "skill_product_inquiry"]
                    ),
                    skills=json.dumps(skills),
                    onboarding=json.dumps(onboarding) if onboarding is not None else None,
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
    except Exception as err:
        print(f"[ApprovalsService] Failed to list approvals: {err}")
        approvals = []
    # 人工决议明细(驳回理由/坐席回复/核准人)埋在 actionPayload 深层,提到顶层供
    # 管理台「审批人 / 驳回理由」列直接消费 —— 此前该列永远显示「-」
    for item in approvals:
        payload = item.get("actionPayload") if isinstance(item.get("actionPayload"), dict) else {}
        item["rejectionReason"] = payload.get("rejectionReason") or None
        item["humanReply"] = payload.get("humanReply") or None
        item["resolvedBy"] = payload.get("resolvedBy") or None
        item["resolvedByRole"] = payload.get("resolvedByRole") or None
    return {"success": True, "approvals": approvals, "total": len(approvals), "tenantId": effective_tenant}


# TS 基线 @Controller(['api/approvals', 'api/chat/approvals']) 双路径别名:
# 前端 useApprovalMachine / useApprovals(发起接管)均 POST /api/chat/approvals,
# Python 移植期曾漏挂该别名致核签按钮 405(wayfinder 004 修复)。
@approvals_router.post("/api/approvals")
@approvals_router.post("/api/chat/approvals")
async def resolve_approval(body: dict, request: Request):
    # 核准人契约(admin-readiness 01):调用方可声明 actor(显示名)+actorRole,
    # 缺省按调用面角色兜底 —— admin 面注入 platform_admin,其余按 merchant_operator。
    # 身份落 actionPayload.resolvedBy/resolvedByRole(engine 侧透传),管理台
    # 「审批人 / 驳回理由」列据此显示真实来源,不再只能显示模糊「人工坐席接管」。
    actor = (body.get("actor") or "").strip()
    actor_role = body.get("actorRole")
    header_role = (request.headers.get("x-role") or "").strip().lower()
    if not actor:
        if header_role == "admin":
            actor, actor_role = "platform_admin", "platform_admin"
        else:
            actor, actor_role = "merchant_operator", "merchant_operator"
    elif not actor_role:
        actor_role = "platform_admin" if header_role == "admin" else "merchant_operator"
    options = {
        "approvalId": body.get("approvalId"),
        "threadId": body.get("threadId"),
        "action": body.get("action"),
        "rejectionReason": body.get("rejectionReason"),
        "humanReply": body.get("humanReply") or body.get("replyMessage"),
        "isFinish": body.get("isFinish"),
        "resolvedBy": actor,
        "resolvedByRole": actor_role,
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
    # 无任何标题来源时诚实标注「未命名 + id 片段」——严禁按 business_id 编造
    # 「Nike 官方售后与质保政策」之类看似真实的文档名(real-data-only,2026-09-13)
    doc_title = (
        meta.get("title")
        or meta.get("docTitle")
        or r.source_url
        or f"未命名知识切片 ({str(r.id)[:8]})"
    )
    category = meta.get("category") or "未分类"
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
    chunkText: str | None = None
    content: str | None = None  # 旧管理台字段别名,与 chunkText 二选一
    businessId: str | None = None
    sourceUrl: str | None = None
    contextualSummary: str | None = None
    metadata: dict | None = None
    title: str | None = None
    category: str | None = None


@router.post("/api/rag/documents", status_code=201)
async def add_rag_document(body: RagDocIn, x_tenant_id: str | None = Header(None)):
    chunk_text = (body.chunkText or body.content or "").strip()
    if not chunk_text:
        raise HTTPException(422, "chunkText (或 content 别名) 不能为空")
    business_id = body.businessId or x_tenant_id or "ecommerce"
    user_meta = body.metadata or {}
    # 用户自拟标题/分类优先,缺省才落平台默认 —— 此前硬编码 "知识文档"/"通用政策" 覆盖入参,
    # 管理台新建切片标题永远显示成兜底名(2026-09-13 修复)
    meta = {
        **user_meta,
        "title": user_meta.get("title") or body.title or "知识文档",
        "category": user_meta.get("category") or body.category or "通用政策",
    }
    async with get_session() as session:
        row = RagDocumentRow(
            business_id=business_id,
            source_url=body.sourceUrl,
            chunk_text=chunk_text,
            contextual_summary=body.contextualSummary or chunk_text[:50],
            # 注意列属性是 metadata_(映射 "metadata" 列):传 metadata= 只会挂到
            # Declarative Base 的保留同名属性上,静默不落库 —— 标题/分类曾因此永远丢失
            metadata_=meta,
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
    category: str | None = None


@router.post("/api/rag/query")
async def rag_query(body: RagQueryIn, x_tenant_id: str | None = Header(None)):
    tenant_id = body.tenantId or x_tenant_id
    # 'all' = 管理台上帝视角:跨租户检索。此前硬编码降级成 ecommerce,
    # 上帝视角永远检不到他租知识(2026-09-13 修复,与 ContextualRAG 全局模式配套)
    biz_id = tenant_id if tenant_id and tenant_id != "all" else None
    rag = ContextualRAG(biz_id)
    results = await rag.search_relevant_docs(body.query, 5, category=body.category)
    if results:
        return {
            "success": True,
            "data": {
                "query": body.query,
                "tenantId": tenant_id or "all",
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
    # 无向量命中时诚实空(real-data-only):检索终点只有真实命中或空,
    # 不再用「前 N 条文档 + 硬编码 0.75 假分数」冒充召回结果 —— 那会让
    # 管理员在演练台上看到完全不相关的「Top 命中」(2026-09-13 拆除)
    return {
        "success": True,
        "data": {
            "query": body.query,
            "tenantId": tenant_id or "all",
            "matches": [],
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


@router.get("/api/conversations/{thread_id}/telemetry")
async def conversation_telemetry(thread_id: str, request: Request):
    """会话级真实决策遥测(real-data-only,2026-09-13):按 LangGraph 节点聚合
    llm_call_logs 的调用次数/Token/成本/延迟 —— 此前管理台「LangGraph 决策流」Tab
    整段是前端编造的假节点耗时/假置信度/假运单号,现全部替换为库内真算;
    无遥测记录时诚实空,严禁合成演示链路。"""
    tenant_id = (
        request.headers.get("x-tenant-id")
        or request.headers.get("x-business-id")
        or request.query_params.get("tenantId")
        or "all"
    )
    clean_tenant = (tenant_id or "").lower().strip()
    params: dict = {"tid": thread_id.strip()}
    tenant_filter = ""
    if clean_tenant and clean_tenant != "all":
        tenant_filter = " AND business_id = :biz"
        params["biz"] = clean_tenant

    async with get_session() as session:
        node_rows = (
            await session.execute(
                text(
                    "SELECT COALESCE(node, 'unknown') AS node, COUNT(*) AS calls, "
                    "COALESCE(SUM(COALESCE(tokens_in, 0) + COALESCE(tokens_out, 0)), 0) AS tokens, "
                    "COALESCE(SUM(cost_usd), 0) AS cost_usd, "
                    "COALESCE(AVG(latency_ms), 0) AS avg_latency_ms, "
                    "COALESCE(SUM(latency_ms), 0) AS total_latency_ms, "
                    "MAX(created_at) AS last_at "
                    "FROM llm_call_logs WHERE thread_id = :tid"
                    f"{tenant_filter} GROUP BY COALESCE(node, 'unknown') ORDER BY MAX(created_at)"
                ).bindparams(**params)
            )
        ).mappings().all()
        total_row = (
            await session.execute(
                text(
                    "SELECT COUNT(*) AS calls, "
                    "COALESCE(SUM(COALESCE(tokens_in, 0) + COALESCE(tokens_out, 0)), 0) AS tokens, "
                    "COALESCE(SUM(cost_usd), 0) AS cost_usd, "
                    "COALESCE(AVG(latency_ms), 0) AS avg_latency_ms, "
                    "COALESCE(SUM(tokens_in), 0) AS tokens_in, "
                    "COALESCE(SUM(tokens_out), 0) AS tokens_out "
                    "FROM llm_call_logs WHERE thread_id = :tid" + tenant_filter
                ).bindparams(**params)
            )
        ).mappings().first()

    nodes = [
        {
            "node": r["node"],
            "calls": int(r["calls"]),
            "tokens": int(r["tokens"]),
            "costUsd": float(r["cost_usd"]),
            "avgLatencyMs": round(float(r["avg_latency_ms"])),
            "totalLatencyMs": int(r["total_latency_ms"]),
            "lastAt": r["last_at"].isoformat() if r["last_at"] else None,
        }
        for r in node_rows
    ]
    totals = {
        "calls": int(total_row["calls"]),
        "tokens": int(total_row["tokens"]),
        "tokensIn": int(total_row["tokens_in"]),
        "tokensOut": int(total_row["tokens_out"]),
        "costUsd": float(total_row["cost_usd"]),
        "avgLatencyMs": round(float(total_row["avg_latency_ms"])),
    }
    return {"success": True, "data": {"threadId": thread_id, "nodes": nodes, "totals": totals}}
