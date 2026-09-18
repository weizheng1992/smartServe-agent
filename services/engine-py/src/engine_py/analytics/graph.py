"""data agent 轻图(15-D1 单轮小图;阶段④):intake → resolve → [clarify | compile → execute] → 卡片。

刻意不接 StepExecutionEngine/审批引擎/planner 快轨(15 号决议);零 HITL;
SSE 由 gateway 侧路由承载,本模块产出结构化轮次结果。
PageContext(19-D3):route/selection/activeFilters 随问题上星,选中实体
进 intent.entity_ids(IN 绑定,阶段②模板已留位)。
"""

from __future__ import annotations

from typing import Any

from .engine import MetricQueryEngine, StructuredQueryIntent, UnsupportedQuery


def build_cards(question: str, result: Any, intent: StructuredQueryIntent | None = None) -> list[dict]:
    """QueryResult → 卡片(表格为主基座;指标元数据+口径注记必带 —— 诚实呈现)。"""
    if not result.rows:
        return [{
            "type": "text",
            "text": f"「{question}」在当前数据下没有匹配结果(诚实空,非错误)。",
            "caliber": result.caliber,
        }]
    rows = result.rows[: intent.limit if intent else len(result.rows)]
    columns = [{"key": k, "label": k} for k in rows[0]]
    return [{
        "type": "table",
        "title": f"{result.metric} · {result.unit}",
        "columns": columns,
        "rows": [{k: (float(v) if isinstance(v, (int, float)) else str(v)) for k, v in r.items()} for r in rows],
        "caliber": result.caliber,
    }]


async def ask(question: str, session_ctx: dict, page_context: dict | None = None) -> dict:
    """一轮问答:intake(含 PageContext)→ resolve → clarify|execute → 卡片。

    返回 {type: clarify|result|unsupported|error, ...}(gateway SSE 直接序列化)。
    """
    engine = MetricQueryEngine(session_ctx=session_ctx)
    from .rbac import allowed_metrics_for_role

    allowed = await allowed_metrics_for_role(session_ctx.get("role", "finance_owner"))
    try:
        intent = engine.resolve(question)
    except UnsupportedQuery as err:
        return {"type": "unsupported", "message": "该问题暂不支持。可试试:销量 Top / 差评榜 / 退款率 / 会话量", "detail": str(err)}

    if isinstance(intent, dict) and intent.get("clarify"):
        return {"type": "clarify", **intent}

    if allowed is not None and intent.metric not in allowed:
        return {
            "type": "unsupported",
            "message": "当前角色无权查看该指标(反问选项集已过滤,此处为直接问越权指标的兜底拒绝)。",
        }

    # PageContext(19-D3):选中实体作为实体过滤(IN 绑定;长度上限 100)
    selection = (page_context or {}).get("selection") or []
    if selection:
        intent = StructuredQueryIntent(
            metric=intent.metric, direction=intent.direction, limit=intent.limit,
            time_window=intent.time_window, category=intent.category,
            entity_ids=[str(s) for s in selection][:100],
        )

    try:
        compiled = engine.compile(intent)
        result = await engine.execute_async(compiled)
    except UnsupportedQuery as err:
        return {"type": "unsupported", "message": "该指标暂未开放", "detail": str(err)}
    except Exception as err:
        return {"type": "error", "message": "查询执行失败(已如实报告,未生成估算数据)", "detail": str(err)}

    cards = build_cards(question, result, intent)
    return {
        "type": "result",
        "metric": result.metric,
        "unit": result.unit,
        "caliber": result.caliber,
        "chart": result.chart,
        "rows": result.rows,
        "cards": cards,
    }
