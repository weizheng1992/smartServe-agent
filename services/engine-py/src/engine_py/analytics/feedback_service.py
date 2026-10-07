"""答案反馈台账服务(反馈闭环 v3.1,2026-10-06):👍/👎 单点写入与扇出。

语义(grill 设计定稿,11 项决策):
- 台账先行:`analytics_feedback` 一次 trace × 一位员工一行,UNIQUE 三元
  upsert,last verdict wins —— 事实源;两池(badcase_candidates /
  query_exemplars)是「行动结果」,由本服务在台账提交后分发。
- 扇出 fire-and-forget:callee 各自开 session(record_badcase_signal /
  add_exemplar 均如此),结构上无法与台账共事务;失败 print 吞掉绝不影响
  反馈主契约(对齐 crud.py persona 删除的坏例信号先例)。
- 改判全补偿:👍→👎 撤**本路径注册**的 user 范例;👎→👍 dismiss 坏例信号
  (candidate 态才可撤,人工裁决优先)。llm/manual 来源的范例永不触碰
  (source 校验 + exemplar_id 仅记本路径产物双保险)。
- 👍 查重:search_exemplar 命中(≥0.90,检索侧自截)即跳过注册 ——
  撤判凭据 exemplar_id 此时必须保持 None,严禁存相似命中他人的范例 id。
"""

from __future__ import annotations

import json
import uuid

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from ..badcase.pool import (
    SOURCE_THUMBS_DOWN,
    dismiss_badcase_signal,
    record_badcase_signal,
)
from ..db import AnalyticsFeedback, AnalyticsTrace, QueryExemplar, get_session
from . import exemplar_service

_UNKNOWN_TRACE = "追踪不存在或已过期,无法反馈"


def _new_feedback_id() -> str:
    return f"fb_{uuid.uuid4().hex[:12]}"


def _exemplar_intent_from_layer(intent: object) -> dict | None:
    """trace intent 层 → exemplar 意图子集(与 L3 自注册 fallback_intent 同六键
    形状);JSONB 回读已是 dict,缺键 .get() 兜底,无 metric 视为不可注册。"""
    if not isinstance(intent, dict) or not intent.get("metric"):
        return None
    return {
        "metric": intent.get("metric"),
        "direction": intent.get("direction") or "DESC",
        "limit": intent.get("limit") or 5,
        "time_window": intent.get("time_window"),
        "category": intent.get("category"),
        "entity_slot": intent.get("entity_slot") or {},
    }


async def _load_exemplar_source(exemplar_id: str) -> str | None:
    """读范例 source(撤判前的 user 归属校验);查无返回 None。"""
    async with get_session() as session:
        row = (
            await session.execute(
                select(QueryExemplar).where(QueryExemplar.id == exemplar_id)
            )
        ).scalar_one_or_none()
        return row.source if row is not None else None


async def submit_feedback(
    business_id: str, staff: str, trace_id: str, verdict: str, note: str | None = None
) -> dict:
    """反馈上行:台账 upsert + 改判补偿 + 两池扇出。

    Returns: {"verdict","badcaseId","exemplarId","reversedFrom"?} |
             {"error": str}(「追踪不存在」前缀由路由映射 404,其余 400)。
    """
    verdict = str(verdict or "").strip()
    trace_id = str(trace_id or "").strip()
    if verdict not in ("up", "down"):
        return {"error": "verdict 必须为 up 或 down"}
    if not trace_id:
        return {"error": "缺少 traceId"}
    if note is not None:  # 空白备注归一为 NULL
        note = str(note).strip() or None

    # ---- Tx1:trace 回查 + 台账 upsert(事实源先行落定) ----
    # commit 会过期 ORM 实例(expire_on_commit),快照列先取平铺本地量
    question = ""
    metric: str | None = None
    intent_layer_intent: dict | None = None
    prior_verdict: str | None = None
    prior_badcase_id: str | None = None
    prior_exemplar_id: str | None = None

    async with get_session() as session:
        trace_row = (
            await session.execute(
                select(AnalyticsTrace)
                .where(
                    AnalyticsTrace.business_id == business_id,
                    AnalyticsTrace.trace_id == trace_id,
                )
                .order_by(AnalyticsTrace.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if trace_row is None:
            # error-key 机器键:路由 _error_response 按 not_found 映射 404
            return {"error": "not_found", "message": _UNKNOWN_TRACE}

        layers = trace_row.layers if isinstance(trace_row.layers, list) else None
        if isinstance(trace_row.layers, str):  # 裸 SQL 写入路径的字符串形态
            try:
                layers = json.loads(trace_row.layers)
            except (ValueError, TypeError):
                layers = None
        intent_layer = next(
            (l for l in (layers or []) if isinstance(l, dict) and l.get("layer") == "intent"),
            None,
        )
        intent_layer_intent = (intent_layer or {}).get("intent")
        question = trace_row.question or ""
        metric = trace_row.final_metric

        prior = (
            await session.execute(
                select(AnalyticsFeedback).where(
                    AnalyticsFeedback.business_id == business_id,
                    AnalyticsFeedback.trace_id == trace_id,
                    AnalyticsFeedback.staff == staff,
                )
            )
        ).scalar_one_or_none()
        if prior is not None:
            prior_verdict = prior.verdict
            prior_badcase_id = prior.badcase_id
            prior_exemplar_id = prior.exemplar_id

        # upsert:改判只覆写事实列;badcase_id/exemplar_id 保留旧值作审计,
        # 新扇出产物的 id 由 Tx2 尽力回写(写失败不追,下次改判仍可补偿)
        stmt = pg_insert(AnalyticsFeedback).values(
            id=_new_feedback_id(),
            business_id=business_id,
            trace_id=trace_id,
            staff=staff,
            verdict=verdict,
            note=note,
            question=question,
            metric=metric,
            layers_json=layers,
        )
        stmt = stmt.on_conflict_do_update(
            constraint="uq_analytics_feedback_staff_trace",
            set_={
                "verdict": stmt.excluded.verdict,
                "note": stmt.excluded.note,
                "question": stmt.excluded.question,
                "metric": stmt.excluded.metric,
                "layers_json": stmt.excluded.layers_json,
                "updated_at": func.now(),
            },
        )
        await session.execute(stmt)
        await session.commit()

    reversed_from = prior_verdict if (prior_verdict and prior_verdict != verdict) else None

    # ---- 台账提交后扇出:各自容错,失败不影响反馈主契约 ----
    badcase_id: str | None = None
    exemplar_id: str | None = None

    if reversed_from == "up" and prior_exemplar_id:
        # 👍→👎:撤「本路径注册」的 user 范例;source 双保险防手工改行错杀
        try:
            if await _load_exemplar_source(prior_exemplar_id) == "user":
                await exemplar_service.deactivate_exemplar(prior_exemplar_id)
                print(f"[Feedback] 改判补偿:撤 user 范例 {prior_exemplar_id}")
        except Exception as err:
            print(f"[Feedback] 撤范例失败(吞掉): {err}")
        exemplar_id = prior_exemplar_id  # 台账审计链保留(已 inactive)

    if reversed_from == "down" and prior_badcase_id:
        # 👎→👍:撤坏例信号(仅 candidate 可撤;已人审则人工优先,静默跳过)
        try:
            await dismiss_badcase_signal(prior_badcase_id)
        except Exception as err:
            print(f"[Feedback] dismiss 坏例失败(吞掉): {err}")

    if verdict == "down":
        try:
            badcase_id = await record_badcase_signal(
                SOURCE_THUMBS_DOWN,
                conversation_ref=trace_id,
                business_id=business_id,
                note=note or question,
                dedupe=True,  # 双击/多帧场景包一轮只入池一次
            )
        except Exception as err:
            print(f"[Feedback] 坏例入池失败(吞掉): {err}")
    elif verdict == "up":
        intent = _exemplar_intent_from_layer(intent_layer_intent)
        if intent is not None:
            try:
                hit = await exemplar_service.search_exemplar(question, business_id)
                if hit is not None:
                    # 查重命中即跳过:exemplar_id 保持 None —— 严禁存相似命中
                    # 的他人范例 id,否则改判撤销会错杀
                    print(f"[Feedback] 👍 查重命中(hit={hit.get('id')}),跳过注册")
                else:
                    exemplar_id = await exemplar_service.add_exemplar(
                        business_id, question, intent, source="user"
                    )
                    print(f"[Feedback] 👍 注册 user 范例 {exemplar_id}")
            except Exception as err:
                print(f"[Feedback] 范例注册失败(吞掉,不影响反馈): {err}")

    # ---- Tx2:新扇出产物 id 尽力回写台账(only-if-obtained,不覆写旧值) ----
    if badcase_id or exemplar_id:
        try:
            values: dict = {"updated_at": func.now()}
            if badcase_id:
                values["badcase_id"] = badcase_id
            if exemplar_id:
                values["exemplar_id"] = exemplar_id
            async with get_session() as session:
                await session.execute(
                    update(AnalyticsFeedback)
                    .where(
                        AnalyticsFeedback.business_id == business_id,
                        AnalyticsFeedback.trace_id == trace_id,
                        AnalyticsFeedback.staff == staff,
                    )
                    .values(**values)
                )
                await session.commit()
        except Exception as err:
            print(f"[Feedback] 台账回写扇出 id 失败(吞掉): {err}")

    return {
        "verdict": verdict,
        "badcaseId": badcase_id or prior_badcase_id,
        "exemplarId": exemplar_id or prior_exemplar_id,
        **({"reversedFrom": reversed_from} if reversed_from else {}),
    }
