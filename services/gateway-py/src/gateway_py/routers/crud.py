"""CRUD 路由组 — guardrails / personas / billing / evals / logs(镜像同控制器,形状 1:1)。"""

from __future__ import annotations

import datetime as _dt
import random
import time

from fastapi import APIRouter, Header, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import desc, select, text

from engine_py.db import (
    EvalRunRecordRow,
    GuardrailRule,
    IntentLog,
    LongMemoryFact,
    SessionMetric,
    TenantBillingQuota,
    get_session,
)

router = APIRouter()


def _date_str(value) -> str:
    return value.isoformat().split("T")[0] if value else "2026-02-23"


# ---------------------------------------------------------------------------
# guardrails
# ---------------------------------------------------------------------------
class GuardrailRuleIn(BaseModel):
    ruleName: str
    ruleType: str
    pattern: str
    action: str | None = None
    severity: str | None = None
    isEnabled: bool | None = None


def _guardrail_item(r: GuardrailRule) -> dict:
    return {
        "id": r.id,
        "tenantId": r.business_id,
        "ruleName": r.rule_name,
        "ruleType": r.rule_type,
        "pattern": r.pattern,
        "action": r.action,
        "severity": r.severity,
        "isEnabled": True if r.is_enabled is None else r.is_enabled,
        "updatedAt": _date_str(r.updated_at),
    }


@router.get("/api/guardrails")
async def list_guardrails(tenantId: str | None = Query(None), x_tenant_id: str | None = Header(None)):
    tenant_id = tenantId or x_tenant_id
    async with get_session() as session:
        stmt = select(GuardrailRule).order_by(desc(GuardrailRule.created_at))
        if tenant_id and tenant_id != "all":
            stmt = stmt.where((GuardrailRule.business_id == tenant_id) | (GuardrailRule.business_id == "all"))
        rows = (await session.execute(stmt)).scalars().all()
    data = [_guardrail_item(r) for r in rows]
    return {"success": True, "tenantId": tenant_id or "all", "total": len(data), "data": data}


@router.post("/api/guardrails", status_code=201)
async def create_guardrail(body: GuardrailRuleIn, x_tenant_id: str | None = Header(None)):
    async with get_session() as session:
        row = GuardrailRule(
            id=f"gr_{int(time.time() * 1000)}",
            business_id=x_tenant_id or "all",
            rule_name=body.ruleName or "未命名安全规则",
            rule_type=body.ruleType or "sensitive_keyword",
            pattern=body.pattern or "",
            action=body.action or "block",
            severity=body.severity or "high",
            is_enabled=True if body.isEnabled is None else body.isEnabled,
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)
    return {"success": True, "data": _guardrail_item(row)}


@router.put("/api/guardrails/{rule_id}")
async def update_guardrail(rule_id: str, body: dict, x_tenant_id: str | None = Header(None)):
    async with get_session() as session:
        row = (await session.execute(select(GuardrailRule).where(GuardrailRule.id == rule_id))).scalar_one_or_none()
        if not row:
            raise HTTPException(404, f"Guardrail rule '{rule_id}' not found in database")
        for key, column in (
            ("ruleName", "rule_name"),
            ("ruleType", "rule_type"),
            ("pattern", "pattern"),
            ("action", "action"),
            ("severity", "severity"),
        ):
            if body.get(key) is not None:
                setattr(row, column, body[key])
        if body.get("isEnabled") is not None:
            row.is_enabled = body["isEnabled"]
        row.updated_at = _dt.datetime.now()
        await session.commit()
        await session.refresh(row)
    return {"success": True, "data": _guardrail_item(row)}


@router.delete("/api/guardrails/{rule_id}")
async def delete_guardrail(rule_id: str, x_tenant_id: str | None = Header(None)):
    async with get_session() as session:
        row = (await session.execute(select(GuardrailRule).where(GuardrailRule.id == rule_id))).scalar_one_or_none()
        if not row:
            raise HTTPException(404, f"Guardrail rule '{rule_id}' not found in database")
        await session.delete(row)
        await session.commit()
    return {"success": True, "message": f"Guardrail rule {rule_id} deleted successfully"}


# ---------------------------------------------------------------------------
# personas
# ---------------------------------------------------------------------------
class PersonaFactIn(BaseModel):
    userId: str
    fact: str
    businessId: str | None = None
    scope: str | None = None
    confidence: float | None = None
    source: str | None = None
    status: str | None = None


def _persona_item(r: LongMemoryFact) -> dict:
    return {
        "id": str(r.id),
        "userId": r.user_id,
        "businessId": r.business_id or "global",
        "scope": r.scope or "tenant",
        "fact": r.fact,
        "confidence": 1.0 if r.confidence is None else r.confidence,
        "source": r.source or "chat_dialogue_inference",
        "status": r.status or "approved",
        "createdAt": _date_str(r.created_at),
    }


@router.get("/api/personas")
async def list_personas(
    tenantId: str | None = Query(None),
    userId: str | None = Query(None),
    x_tenant_id: str | None = Header(None),
):
    tenant_id = tenantId or x_tenant_id
    async with get_session() as session:
        stmt = select(LongMemoryFact).order_by(desc(LongMemoryFact.created_at))
        if tenant_id and tenant_id != "all":
            stmt = stmt.where(LongMemoryFact.business_id == tenant_id)
        if userId:
            stmt = stmt.where(LongMemoryFact.user_id == userId)
        rows = (await session.execute(stmt)).scalars().all()
    data = [_persona_item(r) for r in rows]
    return {"success": True, "tenantId": tenant_id or "all", "total": len(data), "data": data}


@router.post("/api/personas", status_code=201)
async def create_persona(body: PersonaFactIn, x_tenant_id: str | None = Header(None)):
    async with get_session() as session:
        row = LongMemoryFact(
            user_id=body.userId or "u_guest",
            business_id=body.businessId or x_tenant_id or "nike",
            scope=body.scope or "tenant",
            fact=body.fact or "",
            confidence=0.9 if body.confidence is None else body.confidence,
            source=body.source or "admin_manual_input",
            status=body.status or "approved",
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)
    return {"success": True, "data": _persona_item(row)}


@router.put("/api/personas/{fact_id}")
async def update_persona(fact_id: str, body: dict, x_tenant_id: str | None = Header(None)):
    async with get_session() as session:
        row = (
            await session.execute(select(LongMemoryFact).where(LongMemoryFact.id == fact_id))
        ).scalar_one_or_none()
        if not row:
            raise HTTPException(404, f"Persona memory fact '{fact_id}' not found in database")
        if body.get("fact") is not None:
            row.fact = body["fact"]
        if body.get("confidence") is not None:
            row.confidence = body["confidence"]
        if body.get("status") is not None:
            row.status = body["status"]
        await session.commit()
        await session.refresh(row)
    return {"success": True, "data": _persona_item(row)}


@router.delete("/api/personas/{fact_id}")
async def delete_persona(fact_id: str, x_tenant_id: str | None = Header(None)):
    async with get_session() as session:
        row = (
            await session.execute(select(LongMemoryFact).where(LongMemoryFact.id == fact_id))
        ).scalar_one_or_none()
        if not row:
            raise HTTPException(404, f"Persona memory fact '{fact_id}' not found in database")
        await session.delete(row)
        await session.commit()
    return {"success": True, "message": f"Persona fact {fact_id} deleted successfully"}


# ---------------------------------------------------------------------------
# billing
# ---------------------------------------------------------------------------
_TENANT_NAMES = {
    "nike": "Nike 官方旗舰店",
    "adidas": "Adidas 运动专营",
    "ecommerce": "通用电商主站",
}


@router.get("/api/billing/usages")
async def billing_usages():
    async with get_session() as session:
        quotas = (await session.execute(select(TenantBillingQuota))).scalars().all()
        quota_map = {q.business_id: q.monthly_limit_tokens for q in quotas}

        metrics = (
            (
                await session.execute(
                    text(
                        'SELECT "business_id" AS "businessId", '
                        "COALESCE(SUM(total_tokens), 0) AS \"totalTokens\", "
                        "COALESCE(SUM(calculated_cost_usd), 0.0) AS \"costUsd\", "
                        "COUNT(id) AS \"sessionsCount\", "
                        "COALESCE(SUM(CASE WHEN resolution_status = 'resolved_auto' THEN 1 ELSE 0 END), 0) AS \"autoCount\" "
                        "FROM session_metrics GROUP BY business_id"
                    )
                )
            )
            .mappings()
            .all()
        )
        metric_map = {m["businessId"]: m for m in metrics}

    biz_set = set(quota_map) | set(metric_map) or {"nike", "adidas", "ecommerce"}
    data = []
    for biz in sorted(biz_set):
        limit = quota_map.get(biz, 5_000_000)
        m = metric_map.get(biz)
        total_tokens = int(m["totalTokens"]) if m else 0
        sessions_count = int(m["sessionsCount"]) if m else 0
        auto_count = int(m["autoCount"]) if m else 0
        autopilot_rate = round(auto_count / sessions_count, 2) if sessions_count > 0 else 0.95
        usage_rate = total_tokens / limit if limit > 0 else 0
        billing_status = "exceeded" if usage_rate >= 1.0 else "warning" if usage_rate >= 0.8 else "normal"
        data.append(
            {
                "businessId": biz,
                "tenantName": _TENANT_NAMES.get(biz, f"{biz.upper()} 商户"),
                "totalTokens": total_tokens,
                "monthlyLimitTokens": limit,
                "costUsd": float(m["costUsd"]) if m else 0.0,
                "sessionsCount": sessions_count,
                "autopilotRate": autopilot_rate,
                "billingStatus": billing_status,
            }
        )
    return {"success": True, "data": data}


class QuotaIn(BaseModel):
    businessId: str
    monthlyLimitTokens: int


@router.put("/api/billing/quota")
async def update_quota(body: QuotaIn):
    async with get_session() as session:
        existing = (
            await session.execute(select(TenantBillingQuota).where(TenantBillingQuota.business_id == body.businessId))
        ).scalar_one_or_none()
        if existing:
            existing.monthly_limit_tokens = body.monthlyLimitTokens
            existing.updated_at = _dt.datetime.now()
        else:
            session.add(
                TenantBillingQuota(
                    business_id=body.businessId, monthly_limit_tokens=body.monthlyLimitTokens, updated_at=_dt.datetime.now()
                )
            )
        await session.commit()
    usages = await billing_usages()
    found = next((u for u in usages["data"] if u["businessId"] == body.businessId), None)
    return {
        "success": True,
        "data": found
        or {
            "businessId": body.businessId,
            "tenantName": f"{body.businessId.upper()} 商户",
            "totalTokens": 0,
            "monthlyLimitTokens": body.monthlyLimitTokens,
            "costUsd": 0.0,
            "sessionsCount": 0,
            "autopilotRate": 1.0,
            "billingStatus": "normal",
        },
    }


# ---------------------------------------------------------------------------
# evals
# ---------------------------------------------------------------------------
def _eval_item(r: EvalRunRecordRow) -> dict:
    created = r.created_at
    created_str = created.strftime("%Y-%m-%d %H:%M:%S") if created else "2026-02-23 14:00:00"
    return {
        "id": r.id,
        "runName": r.run_name,
        "datasetName": r.dataset_name,
        "sampleCount": r.sample_count,
        "toolAccuracy": 0.95 if r.tool_accuracy is None else r.tool_accuracy,
        "ragFaithfulness": 0.92 if r.rag_faithfulness is None else r.rag_faithfulness,
        "hitlTriggerRate": 0.12 if r.hitl_trigger_rate is None else r.hitl_trigger_rate,
        "status": r.status or "completed",
        "createdAt": created_str,
    }


@router.get("/api/evals/results")
async def eval_results():
    async with get_session() as session:
        rows = (await session.execute(select(EvalRunRecordRow).order_by(desc(EvalRunRecordRow.created_at)))).scalars().all()
    data = [_eval_item(r) for r in rows]
    return {"success": True, "total": len(data), "data": data}


class TriggerEvalIn(BaseModel):
    datasetName: str
    runName: str | None = None


@router.post("/api/evals/run")
async def trigger_eval(body: TriggerEvalIn):
    # 与 TS 一致:本地随机指标生成(非真实评测)
    tool_accuracy = round(0.95 + (random.random() * 0.04 - 0.02), 3)
    rag_faithfulness = round(0.92 + (random.random() * 0.05 - 0.02), 3)
    hitl_rate = round(0.1 + (random.random() * 0.05 - 0.02), 3)
    async with get_session() as session:
        row = EvalRunRecordRow(
            id=f"eval_run_{int(time.time() * 1000)}",
            run_name=body.runName or f"自动化回归评测 - {body.datasetName}",
            dataset_name=body.datasetName,
            sample_count=50,
            tool_accuracy=tool_accuracy,
            rag_faithfulness=rag_faithfulness,
            hitl_trigger_rate=hitl_rate,
            status="completed",
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)
    return {"success": True, "data": _eval_item(row)}


# ---------------------------------------------------------------------------
# system-logs
# ---------------------------------------------------------------------------
@router.get("/api/logs")
async def system_logs(
    request: Request,
    tenantId: str | None = Query(None),
    level: str | None = Query(None),
    limit: int = 50,
):
    async with get_session() as session:
        intent_rows = (
            await session.execute(select(IntentLog).order_by(desc(IntentLog.created_at)).limit(limit))
        ).scalars().all()
        metric_rows = (
            await session.execute(select(SessionMetric).order_by(desc(SessionMetric.created_at)).limit(limit))
        ).scalars().all()

    logs = []
    for l in intent_rows:
        logs.append(
            {
                "id": f"log_intent_{str(l.id)[:8]}",
                "traceId": f"tr_{l.thread_id or 'sys'}",
                "businessId": tenantId if tenantId and tenantId != "all" else "ecommerce",
                "model": "text-embedding-3-small" if l.method == "embedding" else "gpt-4o-mini",
                "promptTokens": 350,
                "completionTokens": 45,
                "totalTokens": 395,
                "latencyMs": 280,
                "statusCode": 200,
                "logType": "intent_triage",
                "rawDetail": {
                    "inputText": l.input_text,
                    "predictedIntents": l.predicted_intents,
                    "confidence": l.confidence,
                },
                "timestamp": l.created_at.strftime("%Y-%m-%d %H:%M:%S") if l.created_at else "2026-02-23 18:00:00",
            }
        )
    for m in metric_rows:
        total_tokens = m.total_tokens or 1000
        logs.append(
            {
                "id": f"log_metric_{str(m.id)[:8]}",
                "traceId": f"tr_{m.thread_id}",
                "businessId": m.business_id,
                "model": "gpt-4o-mini-2024-07-18",
                "promptTokens": int(total_tokens * 0.8),
                "completionTokens": int(total_tokens * 0.2),
                "totalTokens": total_tokens,
                "latencyMs": round(m.avg_latency_ms or 500),
                "statusCode": 200,
                "logType": "llm_call",
                "rawDetail": {
                    "resolutionStatus": m.resolution_status,
                    "costUsd": m.calculated_cost_usd,
                    "nodeTransitionsCount": m.node_transitions_count,
                },
                "timestamp": m.created_at.strftime("%Y-%m-%d %H:%M:%S") if m.created_at else "2026-02-23 18:00:00",
            }
        )

    filtered = [
        r
        for r in logs
        if (not (tenantId and tenantId != "all") or r["businessId"] == tenantId)
        and (not level or r["logType"] == level)
    ]
    return {"success": True, "data": filtered[:limit]}
