"""管理路由组 — tenant / skills / approvals / rag / conversations(镜像同控制器)。"""

from __future__ import annotations

import asyncio
import datetime as _dt
import json
import math
import time
import uuid
from pathlib import Path

from engine_py.analytics import rbac
from engine_py.approvals import ApprovalGatekeeper
from engine_py.approvals.gatekeeper import thread_owner_id  # 线程归属单一实现(gatekeeper)
from engine_py.db import RagDocumentRow, get_session
from engine_py.onboarding import validate_onboarding_config
from engine_py.rag import ContextualRAG
from engine_py.rag.document_ingest import ingest_document_file
from engine_py.rag.document_parse import uploads_root
from engine_py.skills import SkillRegistry
from engine_py.tenant_config import get_tenant_config, update_tenant_skill_config
from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Query, Request, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import desc, select, text
from sqlalchemy.orm import defer

from .. import conversation_repo, tenant_admin
from ..approval_actions import (
    CUSTOMER_ACTIONS,
    OPERATOR_ACTIONS,
    STAFF_REVIEW_ACTIONS,
    actor_from_staff,
    assert_approval_owned,
    assert_thread_owned,
    build_payload,
    human_reply,
    operator_snapshot,
)
from ..tenant_context import get_tenant_context
from ..tenant_scope import (
    StaffIdentity,
    operator_scope,
    optional_staff,
    require_platform_admin,
    require_tenant,
    same_tenant,
)

router = APIRouter()


# ---------------------------------------------------------------------------
# tenant
# ---------------------------------------------------------------------------
@router.get("/api/tenant/ping")
async def tenant_ping(x_tenant_id: str | None = Header(None)):
    ctx = require_tenant()
    config = await get_tenant_config(ctx["tenantId"])
    return {
        "success": True,
        "message": "Tenant context active",
        "tenant": ctx,
        "config": config,
        "timestamp": _dt.datetime.now(_dt.UTC).isoformat(),
    }


@router.get("/api/overview")
async def platform_overview(_platform: StaffIdentity = Depends(require_platform_admin)):
    """全局指标大盘聚合端点(admin-readiness 03,real-data-only):一次请求出全部
    卡片,全部库内真算 —— 活跃租户(近7天 session_metrics 有落账)、会话状态分布、
    待审批 HITL 工单(含最老积压)、Token/成本(session_metrics SUM,与计费页同源)、
    Autopilot 率(resolved_auto 占比,替换 README 编造的 94.2%)、人工接管会话数、
    LLM 调用近 24h(llm_call_logs)。README 的「在线客服坐席」无在线状态数据源,
    诚实不做假指标,以「人工接管会话数」替代。"""
    async with get_session() as session:
        active_tenants = (
            await session.execute(
                text(
                    "SELECT COUNT(DISTINCT business_id) FROM session_metrics "
                    "WHERE created_at >= NOW() - INTERVAL '7 days'"
                )
            )
        ).scalar_one()

        status_rows = (
            (
                await session.execute(
                    text("SELECT resolution_status, COUNT(*) AS n FROM session_metrics GROUP BY resolution_status")
                )
            )
            .mappings()
            .all()
        )
        session_distribution = {r["resolution_status"]: int(r["n"]) for r in status_rows}
        total_sessions = sum(session_distribution.values())
        resolved_auto = session_distribution.get("resolved_auto", 0)

        thread_rows = (
            (await session.execute(text("SELECT status, COUNT(*) AS n FROM threads GROUP BY status"))).mappings().all()
        )
        thread_distribution = {r["status"]: int(r["n"]) for r in thread_rows}

        human_takeover = (
            await session.execute(text("SELECT COUNT(*) FROM threads WHERE assigned_operator_id IS NOT NULL"))
        ).scalar_one()

        waiting_row = (
            (
                await session.execute(
                    text(
                        "SELECT COUNT(*) AS n, "
                        "COALESCE(EXTRACT(EPOCH FROM (NOW() - MIN(created_at))) / 60, 0) AS oldest_minutes "
                        "FROM pending_approvals WHERE status = 'waiting'"
                    )
                )
            )
            .mappings()
            .first()
        )

        usage_row = (
            (
                await session.execute(
                    text(
                        "SELECT COALESCE(SUM(total_tokens), 0) AS tokens, "
                        "COALESCE(SUM(calculated_cost_usd), 0) AS cost FROM session_metrics"
                    )
                )
            )
            .mappings()
            .first()
        )

        llm_row = (
            (
                await session.execute(
                    text(
                        "SELECT COUNT(*) AS calls, COALESCE(SUM(cost_usd), 0) AS cost, "
                        "COALESCE(AVG(latency_ms), 0) AS avg_latency "
                        "FROM llm_call_logs WHERE created_at >= NOW() - INTERVAL '24 hours'"
                    )
                )
            )
            .mappings()
            .first()
        )

    return {
        "success": True,
        "data": {
            "activeTenants": int(active_tenants),
            "sessions": {"total": total_sessions, "distribution": session_distribution},
            "threads": {"distribution": thread_distribution, "humanTakeover": int(human_takeover)},
            "approvals": {
                "waiting": int(waiting_row["n"]),
                "oldestWaitingMinutes": round(float(waiting_row["oldest_minutes"])),
            },
            "usage": {"tokens": int(usage_row["tokens"]), "costUsd": float(usage_row["cost"])},
            "autopilotRate": round(resolved_auto / total_sessions, 4) if total_sessions else 0,
            "llm24h": {
                "calls": int(llm_row["calls"]),
                "costUsd": float(llm_row["cost"]),
                "avgLatencyMs": round(float(llm_row["avg_latency"])),
            },
        },
    }


@router.get("/api/tenant/list")
async def tenant_list(_platform: StaffIdentity = Depends(require_platform_admin)):
    try:
        tenants = await tenant_admin.list_tenant_summaries()
        return {"success": True, "tenants": tenants}
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
async def create_tenant(body: TenantCreateIn, _platform: StaffIdentity = Depends(require_platform_admin)):
    clean_id = (body.id or "").lower().strip()
    if not clean_id or not body.name:
        raise HTTPException(400, "Tenant ID and Name are required")

    cfg = body.config or {}
    # 与 PUT 同语义的服务端 schema 校验:JSON 手编错形诚实失败(400),
    # 而非落库后在首访欢迎/引擎旁路两处静默回落平台默认
    if body.onboardingConfig is not None:
        onboarding_errors = validate_onboarding_config(body.onboardingConfig)
        if onboarding_errors:
            raise HTTPException(400, f"onboardingConfig 校验失败: {'; '.join(onboarding_errors)}")

    # SQL 与配置组装语义在 tenant_admin 域(架构审查 #6);平铺字段与嵌套
    # config 取并集(平铺优先)是本 DTO 的呈现语义,留在适配层
    await tenant_admin.upsert_tenant(
        business_id=clean_id,
        name=body.name,
        status=body.status,
        industry=body.industry or cfg.get("industry"),
        webhook_url=body.webhookUrl or cfg.get("webhookUrl"),
        api_key=body.apiKey,
        refund_limit=body.refundLimit if body.refundLimit is not None else cfg.get("refundLimit"),
        onboarding_config=body.onboardingConfig,
    )
    return {"success": True, "businessId": clean_id}


@router.put("/api/tenant/{business_id}")
async def update_tenant(business_id: str, body: TenantUpdateIn, _platform: StaffIdentity = Depends(require_platform_admin)):
    clean_id = business_id.lower().strip()
    if not body.name:
        raise HTTPException(400, "Tenant Name is required")

    # 服务端 schema 校验(new-user-onboarding E):JSON 手编错形必须诚实失败
    if body.onboardingConfig is not None:
        onboarding_errors = validate_onboarding_config(body.onboardingConfig)
        if onboarding_errors:
            raise HTTPException(400, f"onboardingConfig 校验失败: {'; '.join(onboarding_errors)}")

    try:
        await tenant_admin.update_tenant(
            business_id=clean_id,
            name=body.name,
            status=body.status,
            industry=body.industry,
            webhook_url=body.webhookUrl,
            api_key=body.apiKey,
            refund_limit=body.refundLimit,
            onboarding_config=body.onboardingConfig,
        )
    except LookupError as err:
        raise HTTPException(404, str(err)) from None
    except PermissionError as err:
        raise HTTPException(403, str(err)) from None
    return {"success": True, "businessId": clean_id}


@router.delete("/api/tenant/{business_id}")
async def delete_tenant(business_id: str, _platform: StaffIdentity = Depends(require_platform_admin)):
    try:
        await tenant_admin.delete_tenant(business_id=business_id.lower().strip())
    except PermissionError as err:
        raise HTTPException(403, str(err)) from None
    return {"success": True}


# ---------------------------------------------------------------------------
# skills
# ---------------------------------------------------------------------------
@router.get("/api/skills/registry")
async def skills_registry(_platform: StaffIdentity = Depends(require_platform_admin)):
    return {"success": True, "skills": [s.metadata for s in SkillRegistry.get_all_skills()]}


@router.get("/api/skills/config")
async def skills_config(_platform: StaffIdentity = Depends(require_platform_admin), x_tenant_id: str | None = Header(None)):
    ctx = require_tenant()
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
async def update_skills_config(body: dict, _platform: StaffIdentity = Depends(require_platform_admin), x_tenant_id: str | None = Header(None)):
    ctx = require_tenant()
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
async def skills_tenant_alias(_platform: StaffIdentity = Depends(require_platform_admin), x_tenant_id: str | None = Header(None)):
    ctx = require_tenant()
    skills = await _tenant_skills(ctx["tenantId"])
    return {"success": True, "tenantId": ctx["tenantId"], "skills": skills}


@router.patch("/api/skills/tenant/{skill_id}")
async def update_tenant_skill(skill_id: str, body: dict, _platform: StaffIdentity = Depends(require_platform_admin), x_tenant_id: str | None = Header(None)):
    ctx = require_tenant()
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
    authorization: str | None = Header(None),
):
    ctx = get_tenant_context()
    effective_tenant = tenantId or businessId or (ctx or {}).get("tenantId")
    # 13 GET 收口(最小面):持员工 JWT 时列表按本租户收窄,显式租户参数与
    # 本租户不一致 403(与 POST 员工路径对象级同口径)。裸匿名维持放行但
    # 2026-10-23 起脱敏(见下方 redaction 块)—— apps/web 顾客审批卡轮询与
    # admin 大盘依赖匿名可达,硬切 401 仍归票 14(apps/web 接线)同批收紧;
    # 顾客 JWT/属主过滤面届时一并落。
    staff = await optional_staff(authorization)
    if staff is not None:
        staff_tenant = staff.staff.business_id
        if effective_tenant and not same_tenant(effective_tenant, staff_tenant):
            raise HTTPException(status_code=403, detail="租户不一致,拒绝跨租户审批列表")
        effective_tenant = staff_tenant
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
    if staff is None:
        # 匿名脱敏(2026-10-23 生产审计收口):匿名列表不再吐 userEmail/userId/
        # actionPayload 与决议人字段 —— 防两点:PII 直出(订单号/金额/邮箱),与
        # 「GET 喂 POST」组合链(此前匿名 GET 泄漏属主 userId,POST 自报该 userId
        # 即过线程归属闸,可匿名核准/驳回退款)。apps/web 顾客卡仅消费 id/
        # threadId/actionType/status/createdAt(动作提交的 userId 来自会话),
        # 员工 JWT 路径(admin 大盘/merchant-admin)全量不变;票 14 落地整体收紧。
        for item in approvals:
            item["userEmail"] = None
            item["userId"] = None
            item["actionPayload"] = None
            item["rejectionReason"] = None
            item["humanReply"] = None
            item["resolvedBy"] = None
            item["resolvedByRole"] = None
    return {"success": True, "approvals": approvals, "total": len(approvals), "tenantId": effective_tenant}


# TS 基线 @Controller(['api/approvals', 'api/chat/approvals']) 双路径别名:
# 前端 useApprovalMachine / useApprovals(发起接管)均 POST /api/chat/approvals,
# Python 移植期曾漏挂该别名致核签按钮 405(wayfinder 004 修复)。

# 02 安全先行(2026-09-27):本面是双面接口 —— 顾客 HITL(apps/web 审批卡/
# 呼叫人工)与历史坐席通道共用。分面收口:人工坐席动作(human_message/
# human_finish)必须持员工 JWT;顾客动作(approve/reject/cancel/
# start_human_takeover)保持可达但加线程归属绑定(userId 必须等于 thread 属主,
# 此前匿名可凭猜测的 approvalId 核准退款)。x-role 自报头与匿名 actor 自报
# 一并退役 —— 身份只来自 JWT 或「顾客」语义。GET 列表收口另行立项(_apps/web
# 轮询与 admin 大盘都依赖匿名 GET)。
# 动作词表上收 approval_actions(架构审查 #2):CUSTOMER_ACTIONS /
# OPERATOR_ACTIONS / STAFF_REVIEW_ACTIONS 是三通道共享的领域词汇唯一权威。
# P1(spec §2.1):release_takeover 为线程级员工动作。P4(spec §2.7):human_reply
# 退役 —— 坐席发言一律走 socket send_message,白名单移除即 400;human_finish
# 仍有 useApprovalMachine(禁区 admin/web)消费,退役挪 P5。


# 可选身份闸上收 tenant_scope(架构审查 #1):_optional_staff → optional_staff,
# 坏 token 401 与非员工 None 语义不变;返回 StaffIdentity(属性访问)。


@approvals_router.post("/api/approvals")
@approvals_router.post("/api/chat/approvals")
async def resolve_approval(body: dict, request: Request, authorization: str | None = Header(None)):
    action = (body.get("action") or "").strip()
    if action not in CUSTOMER_ACTIONS | OPERATOR_ACTIONS:
        # 诚实失败:此前未知动作会落到引擎按驳回语义处理(静默错误终局)
        raise HTTPException(status_code=400, detail=f"未知审批动作: {action or '(空)'}")

    staff_ctx = await optional_staff(authorization)

    if staff_ctx is not None:
        # 员工路径对象级租户校验(与商户面 A4 同口径):无论坐席动作还是代行
        # 顾客动作,他租审批单一律 403 —— 否则员工可跨租户发消息/核准退款。
        # 闸机制上收 approval_actions.assert_*(detail 形,文案契约钉死)。
        tenant = staff_ctx.staff.business_id
        await assert_approval_owned(body.get("approvalId"), tenant)
        # release_takeover 是线程级动作(无审批单):按线程归属校验租户,严防
        # 员工凭猜测的 threadId 跨租户释放他人接管会话;归属未知 fail-open。
        if action == "release_takeover":
            await assert_thread_owned(body.get("threadId"), tenant)
        # P4 台内一等批驳(spec §2.6):员工代行批/驳须持 live_desk:approve ——
        # 退款核准是资金语义,不放给无批驳权限的普通坐席(查询 perms_for_role,
        # finance_owner 兜底全量,与 live_desk:operate 闸同查法)。
        if action in STAFF_REVIEW_ACTIONS:
            staff = staff_ctx.staff
            if "live_desk:approve" not in await rbac.perms_for_role(staff.business_id, staff.role):
                raise HTTPException(status_code=403, detail="无工单批驳权限(live_desk:approve)")

    if action in OPERATOR_ACTIONS:
        if staff_ctx is None:
            raise HTTPException(
                status_code=401,
                detail="人工坐席操作须经员工登录(管理台请走 /api/admin/approvals 通道)",
            )
        actor, actor_role = actor_from_staff(
            staff_ctx.staff, body_actor=body.get("actor"), body_role=body.get("actorRole")
        )
    elif staff_ctx is not None:
        actor, actor_role = actor_from_staff(
            staff_ctx.staff, body_actor=body.get("actor"), body_role=body.get("actorRole")
        )
    else:
        # 顾客动作:线程归属绑定 —— userId(body 或 x-user-id 头)必须是会话属主。
        # 审批单/线程均不可解析时不额外造 403(落引擎自身 404/格式无效语义;
        # UUID 主键本就不可枚举,存在性探测无增益)。
        user_id = str(body.get("userId") or request.headers.get("x-user-id") or "").strip()
        if not user_id:
            raise HTTPException(status_code=400, detail="缺少 userId,无法核验会话归属")
        thread_id = body.get("threadId")
        record = None
        if not thread_id and body.get("approvalId"):
            record = await ApprovalGatekeeper.find_approval_by_id(body["approvalId"])
            thread_id = (record or {}).get("threadId")
        if body.get("threadId") or record is not None:
            owner = await thread_owner_id(thread_id)
            if owner != user_id:
                raise HTTPException(status_code=403, detail="会话归属校验失败,拒绝顾客侧操作")
        actor, actor_role = "customer", "customer"

    # 核准人契约(admin-readiness 01):身份落 actionPayload.resolvedBy/
    # resolvedByRole(engine 侧透传),管理台「审批人 / 驳回理由」列据此显示
    # 真实来源;customer 语义经 02 收口入引擎词表,不再伪装成运营坐席。
    # P1 坐席身份(spec §2.2):operator 快照由服务端从员工 JWT 派生,客户端自报不采信。
    return await ApprovalGatekeeper.process_approval_action(
        build_payload(
            approval_id=body.get("approvalId"),
            thread_id=body.get("threadId"),
            action=action,
            rejection_reason=body.get("rejectionReason"),
            human_reply_value=human_reply(body.get("humanReply"), body.get("replyMessage")),
            is_finish=body.get("isFinish"),
            resolved_by=actor,
            resolved_by_role=actor_role,
            operator=(
                operator_snapshot(staff_ctx.email, staff_ctx.staff.display_name)
                if staff_ctx is not None
                else None
            ),
        )
    )


# ---------------------------------------------------------------------------
# rag
# ---------------------------------------------------------------------------
@router.get("/api/rag/documents")
async def rag_documents(_platform: StaffIdentity = Depends(require_platform_admin), tenantId: str | None = Query(None), x_tenant_id: str | None = Header(None)):
    tenant_id = tenantId or x_tenant_id
    async with get_session() as session:
        # 列表页封顶 + 免拉 embedding 列(2026-09-28 夜审):此前无界全量且整行
        # 取回 —— 每切片 384 维 JSON 串(_rag_item 用不到)全进内存,文档量增长
        # 后该端点线性变重。响应形状不变(total = 实返条数),取最新 500 条。
        stmt = (
            select(RagDocumentRow)
            .options(defer(RagDocumentRow.embedding))
            .order_by(desc(RagDocumentRow.created_at))
            .limit(500)
        )
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
async def add_rag_document(body: RagDocIn, _platform: StaffIdentity = Depends(require_platform_admin), x_tenant_id: str | None = Header(None)):
    chunk_text = (body.chunkText or body.content or "").strip()
    if not chunk_text:
        raise HTTPException(422, "chunkText (或 content 别名) 不能为空")
    # 具名租户强制(2026-10-17 窃听族收口 sec-2):语料是聊天 prompt 的检索来源,
    # 租户归属是写侧决策。此前 body 具名即可直入任意租户语料、缺省兜底
    # "ecommerce" 静默落演示租户 —— 与 upload 同律,'all' 上帝视角严禁直入。
    business_id = (body.businessId or x_tenant_id or "").strip()
    if not business_id or business_id == "all":
        raise HTTPException(400, "租户必须显式具名(businessId 或 x-tenant-id),'all' 严禁直入语料")
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
async def delete_rag_document(doc_id: str, _platform: StaffIdentity = Depends(require_platform_admin), tenantId: str | None = Query(None), x_tenant_id: str | None = Header(None)):
    # 具名租户强制(2026-10-17 窃听族收口 sec-2):空头曾免 WHERE,凭 doc_id
    # 即可删任意租户文档。'all' 上帝视角严禁挂删除。
    tenant_id = (tenantId or x_tenant_id or "").strip()
    if not tenant_id or tenant_id == "all":
        raise HTTPException(400, "删除必须显式具名租户(tenantId 或 x-tenant-id),'all' 严禁")
    async with get_session() as session:
        stmt = select(RagDocumentRow).where(RagDocumentRow.id == doc_id, RagDocumentRow.business_id == tenant_id)
        row = (await session.execute(stmt)).scalar_one_or_none()
        if not row:
            raise HTTPException(404, f"Document with ID '{doc_id}' not found in database")
        await session.delete(row)
        await session.commit()
    return {"success": True, "message": f"Document {doc_id} deleted successfully"}


# ---- 文档上传摄取(2026-10-17 文档 RAG,路由计数 129→130)----
# 与 chat.py 图片上传同纪律:不信任客户端声明,真实类型以文件头魔数自证;
# 大小以读流实测为准。同名文件重复上传 = 同 source_url 整组替换(版本演进
# 语义,与 knowledge_files 文件级替换一致)。摄取为同步 v1(docling + VLM
# 字幕在请求内完成,大文档秒到分钟级);异步作业化是 v2 裁决项。
_MAX_DOC_UPLOAD_BYTES = 20 * 1024 * 1024
_DOC_UPLOAD_CHUNK_BYTES = 256 * 1024


def _sniff_doc_kind(head: bytes) -> str | None:
    """文件头魔数 → 规范扩展名;不认识返回 None。docx 是 zip 容器(PK\x03\x04);
    .doc 是 OLE2 复合文档(D0 CF 11 E0)—— 放行到引擎侧给「另存为 .docx」的
    诚实错误,比在网关吞掉更可诊断。"""
    if head.startswith(b"%PDF-"):
        return ".pdf"
    if head.startswith(b"PK\x03\x04"):
        return ".docx"
    if head.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
        return ".doc"
    return None


def _rag_docs_dir():
    target = uploads_root() / "rag" / "docs"
    target.mkdir(parents=True, exist_ok=True)
    return target


@router.post("/api/rag/documents/upload", status_code=202)
async def upload_rag_document(
    request: Request,
    file: UploadFile = File(...),
    businessId: str | None = Form(None),
    category: str | None = Form(None),
    x_tenant_id: str | None = Header(None),
    _platform: StaffIdentity = Depends(require_platform_admin),
):
    """上传 PDF/Word 文档,异步摄取(202 返回 jobId,轮询 jobs/{id} 状态)。

    摄取管线(docling+VLM+granite 抽数)在后台任务执行:闸门(租户/魔数/限长)
    同步快败,落盘后立即受理。平台闸与手写切片写(POST /api/rag/documents)
    同律 —— 20MB 重管线是最贵写面,不能只靠具名租户 400 + 30/60 限流兜着
    (匿名面严禁触达);轮询端点 jobId 即能力令牌维持文档化豁免。

    租户必须显式具名(businessId 表单字段或 x-tenant-id 头),'all' 上帝视角
    严禁挂载摄取 —— 租户归属是写侧决策,缺省猜测曾把 aurora 货架挂到演示
    租户名下(product_knowledge 帐篷幻觉先例)。摄取失败/扫描件空内容 422
    透出诚实原因,落盘文件同批清理。文件名只作展示用 source_url(同名重传
    即整组替换),落盘一律 UUID 命名,无路径穿越面。
    """
    business_id = (businessId or x_tenant_id or "").strip()
    if not business_id or business_id == "all":
        raise HTTPException(400, "文档摄取必须指定具名租户 businessId,严禁 'all' 上帝视角挂载或缺省猜测")
    # 声明长度前置闸(2026-10-17 对抗审查):starlette 对 multipart 在进 handler
    # 前就把整个 body spool 落盘,读流限长是事后闸 —— 超大 body 会先填临时盘。
    # Content-Length 客户端可谎报,故只作廉价前置拒绝(声明合规才进读流实测);
    # 分块传输无 CL 时放行,由读流闸兜底。+64KB 容 multipart 表单结构开销。
    try:
        declared_length = int(request.headers.get("content-length") or 0)
    except ValueError:
        declared_length = 0
    if declared_length > _MAX_DOC_UPLOAD_BYTES + 64 * 1024:
        raise HTTPException(413, "文档超过 20MB 上限")

    target = _rag_docs_dir() / f"{uuid.uuid4().hex}.bin"
    out = None
    out_path = target
    header = b""
    written = 0
    try:
        while chunk := await file.read(_DOC_UPLOAD_CHUNK_BYTES):
            written += len(chunk)
            if written > _MAX_DOC_UPLOAD_BYTES:
                raise HTTPException(413, "文档超过 20MB 上限")
            if out is None:
                # 首块嗅探只取截断副本,写入仍用完整块(chat.py 同纪律)
                header = (header + chunk)[:16]
                if len(header) >= 8:  # 最长魔数 OLE2 8 字节
                    kind = _sniff_doc_kind(header)
                    if kind is None:
                        raise HTTPException(400, "不支持的文档类型,仅限 pdf / docx")
                    out_path = target.with_suffix(kind)
                    out = out_path.open("wb")
            if out is not None:
                out.write(chunk)
    except HTTPException:
        out_path.unlink(missing_ok=True)  # 半截文件不许残留(close 在 finally 幂等收口)
        raise
    finally:
        await file.close()
        if out is not None:
            out.close()

    if out is None:
        raise HTTPException(400, "不支持的文档类型,仅限 pdf / docx(短于魔数长度的残流必然不符)")
    if out_path.suffix == ".doc":
        out_path.unlink(missing_ok=True)
        raise HTTPException(422, "老式 .doc 二进制格式暂不支持,请先用 Word/WPS 另存为 .docx 或导出 PDF 后重试")

    original_name = Path(file.filename or out_path.name).name
    if len(original_name) > 200:
        original_name = original_name[-200:]

    # 异步作业化(v2,2026-10-18):docling+VLM+granite 抽数的摄取管线在网关
    # 进程内跑秒到分钟级,同步占位曾把管理请求钉在「解析中…」。闸门(租户/
    # 魔数/限长)保持同步快败,落盘后即 202 派后台任务,状态写 Redis(TTL 1h,
    # 免迁移;单实例假设 ADR-0007,网关重启在途任务失联 → 状态端点按账龄
    # 诚实降级 stale 提示重传)。jobId 为随机 uuid 能力令牌。
    job_id = uuid.uuid4().hex
    await _write_ingest_job(
        job_id,
        {
            "status": "processing",
            "sourceUrl": original_name,
            "createdAt": time.time(),
            "businessId": business_id,
        },
    )
    task = asyncio.create_task(
        _run_ingest_job(
            job_id,
            out_path,
            business_id,
            (category or "").strip() or "document",
            original_name,
        )
    )
    _INGEST_TASKS.add(task)
    task.add_done_callback(_INGEST_TASKS.discard)
    return JSONResponse(
        status_code=202,
        content={"success": True, "data": {"jobId": job_id, "sourceUrl": original_name, "status": "processing"}},
    )


# 后台摄取任务的强引用集(asyncio.create_task 弱引用会被 GC 的已知坑)
_INGEST_TASKS: set[asyncio.Task] = set()
_INGEST_JOB_TTL_SECONDS = 3600
_INGEST_JOB_STALE_SECONDS = 900  # processing 超过 15 分钟视为失联(网关重启)


async def _write_ingest_job(job_id: str, payload: dict) -> None:
    from engine_py.event_bus import get_client as get_redis

    redis = await get_redis()
    await redis.set(
        f"rag:ingest_job:{job_id}",
        json.dumps(payload, ensure_ascii=False),
        ex=_INGEST_JOB_TTL_SECONDS,
    )


async def _read_ingest_job(job_id: str) -> dict | None:
    from engine_py.event_bus import get_client as get_redis

    redis = await get_redis()
    raw = await redis.get(f"rag:ingest_job:{job_id}")
    return json.loads(raw) if raw else None


async def _run_ingest_job(
    job_id: str,
    file_path: Path,
    business_id: str,
    category: str,
    original_name: str,
) -> None:
    """后台摄取任务:结果(含失败)写 Redis 作业状态;失败同批清理落盘文件。"""
    try:
        result = await ingest_document_file(
            file_path,
            business_id,
            category=category,
            caption_images=True,
            source_url=original_name,
        )
    except Exception as err:
        file_path.unlink(missing_ok=True)
        await _write_ingest_job(
            job_id,
            {"status": "failed", "error": f"文档摄取异常: {err}", "sourceUrl": original_name, "createdAt": time.time()},
        )
        print(f"[RAG Upload] 作业 {job_id[:8]} 摄取异常: {err}")
        return
    if result.status != "ingested":
        file_path.unlink(missing_ok=True)
        await _write_ingest_job(
            job_id,
            {
                "status": result.status,
                "error": result.reason or "未知原因",
                "sourceUrl": original_name,
                "createdAt": time.time(),
            },
        )
        return
    await _write_ingest_job(
        job_id,
        {
            "status": "completed",
            "sourceUrl": original_name,
            "docTitle": result.doc_title,
            "chunks": result.chunks,
            "tables": result.tables,
            "images": result.images,
            "captioned": result.captioned,
            "partial": result.partial,
            "createdAt": time.time(),
        },
    )


@router.get("/api/rag/documents/upload/jobs/{job_id}")
async def rag_upload_job_status(job_id: str):
    """上传作业状态轮询端点。jobId 为随机 uuid 能力令牌(不校验租户);
    processing 超过 15 分钟诚实降级 stale(疑似网关重启,任务失联),提示重传。"""
    payload = await _read_ingest_job(job_id)
    if payload is None:
        raise HTTPException(404, f"上传作业 {job_id} 不存在或已过期(TTL 1 小时)")
    if payload.get("status") == "processing":
        age = time.time() - float(payload.get("createdAt") or 0)
        if age > _INGEST_JOB_STALE_SECONDS:
            payload["status"] = "stale"
            payload["error"] = "处理超时(疑似网关重启,任务失联),请重新上传"
    return {"success": True, "data": payload}


class RagQueryIn(BaseModel):
    query: str
    tenantId: str | None = None
    category: str | None = None


@router.post("/api/rag/query")
async def rag_query(body: RagQueryIn, _platform: StaffIdentity = Depends(require_platform_admin), x_tenant_id: str | None = Header(None)):
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
    tenantId: str | None = Query(None),
    authorization: str | None = Header(None),
):
    # 坐席/管控双面闸(2026-10-18 窃听族收口 sec-1 收尾):员工 JWT 必需,
    # platform_admin 跨租户(缺省 'all',tenantId query 显式选租户),普通员工
    # 钉本租户(参数对其忽略)—— 四源自报头 + 'ecommerce' 兜底链退役
    tenant_id, _identity = await operator_scope(authorization, tenantId)

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
async def get_conversation(
    thread_id: str,
    tenantId: str | None = Query(None),
    authorization: str | None = Header(None),
):
    # 属主闸收口(sec-1 实弹:此前匿名可凭 thread_id 读任意租户会话,timeline
    # 租户闸在租户为 None 时整段跳过)—— operator_scope 后租户恒有权威来源
    tenant_id, _identity = await operator_scope(authorization, tenantId)
    timeline = await conversation_repo.get_conversation_timeline(thread_id, tenant_id)
    return {"success": True, "data": timeline}


class ConversationStatusIn(BaseModel):
    status: str
    assignedOperatorId: str | None = None
    tags: list[str] | None = None


@router.post("/api/conversations/{thread_id}/status")
async def update_conversation_status(
    thread_id: str,
    body: ConversationStatusIn,
    tenantId: str | None = Query(None),
    authorization: str | None = Header(None),
):
    tenant_id, _identity = await operator_scope(authorization, tenantId)
    updated = await conversation_repo.update_conversation_status(
        thread_id, tenant_id, body.status, body.assignedOperatorId, body.tags
    )
    if not updated:
        raise HTTPException(404, f"Conversation '{thread_id}' not found")
    return {"success": True, "data": updated}


@router.get("/api/conversations/{thread_id}/telemetry")
async def conversation_telemetry(
    thread_id: str,
    tenantId: str | None = Query(None),
    authorization: str | None = Header(None),
):
    """会话级真实决策遥测(real-data-only,2026-09-13):按 LangGraph 节点聚合
    llm_call_logs 的调用次数/Token/成本/延迟 —— 此前管理台「LangGraph 决策流」Tab
    整段是前端编造的假节点耗时/假置信度/假运单号,现全部替换为库内真算;
    无遥测记录时诚实空,严禁合成演示链路。"""
    tenant_id, _identity = await operator_scope(authorization, tenantId)
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
