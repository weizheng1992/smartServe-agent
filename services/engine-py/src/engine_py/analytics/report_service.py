"""报告服务(14 号;阶段⑤):四族指标批量执行 → 单页 HTML + rows_json 落库。

不变量(14-D3):数字全部来自真实查询(同一 MetricQueryEngine/权限/沙箱);
LLM 只组织结论语言 —— 本模块结论段为模板拼接(不编造任何数字),LLM 润色
属阶段⑤后续接缝,缺席时报告照常成立。
"""

from __future__ import annotations

import csv
import io
import json
import uuid
from datetime import datetime

from sqlalchemy import select

from ..db import AnalyticsReport, get_session
from .engine import MetricQueryEngine, UnsupportedQuery

REPORT_METRICS = ["gmv", "volume", "refund_rate", "session_volume"]


def _html_report(title: str, sections: list[dict]) -> str:
    blocks = []
    for s in sections:
        rows_html = "".join(
            "<tr>" + "".join(f"<td>{v}</td>" for v in r.values()) + "</tr>" for r in s["rows"][:5]
        )
        head_html = "".join(f"<th>{k}</th>" for k in (s["rows"][0] if s["rows"] else {}))
        blocks.append(
            f"<section><h3>{s['metric']}({s['unit']})</h3>"
            f"<p class='caliber'>口径:{s['caliber']}</p>"
            f"<table><thead><tr>{head_html}</tr></thead><tbody>{rows_html}</tbody></table></section>"
        )
    return (
        "<!doctype html><html lang='zh-CN'><meta charset='utf-8'>"
        f"<title>{title}</title><style>body{{font-family:sans-serif;margin:24px}}"
        "table{{border-collapse:collapse;margin:8px 0}}td,th{{border:1px solid #ccc;padding:4px 10px;font-size:13px}}"
        ".caliber{{color:#888;font-size:12px}}</style>"
        f"<h1>{title}</h1><p>数字全部来自真实查询;结论由模板拼接,未编造任何数字。</p>"
        + "".join(blocks)
        + "</html>"
    )


async def generate_report(business_id: str, generated_by: str, time_window: dict | None = None) -> dict:
    """四族批量执行 → 落库 analytics_reports;单指标失败如实记入 sections(error 行)。"""
    engine = MetricQueryEngine(session_ctx={"business_id": business_id, "role": "finance_owner"})
    sections: list[dict] = []
    rows_all: dict[str, list] = {}
    for metric in REPORT_METRICS:
        try:
            from .engine import StructuredQueryIntent

            intent = StructuredQueryIntent(metric=metric, direction="DESC", limit=5, time_window=time_window)
            result = await engine.execute_async(engine.compile(intent))
            sections.append({"metric": result.metric, "unit": result.unit, "caliber": result.caliber, "rows": result.rows})
            rows_all[metric] = result.rows
        except (UnsupportedQuery, Exception) as err:
            sections.append({"metric": metric, "unit": "-", "caliber": f"该指标执行失败:{err}", "rows": []})
            rows_all[metric] = []

    title = f"{business_id} 经营报告 · {datetime.now().strftime('%Y-%m-%d')}"
    html = _html_report(title, sections)
    report_id = f"rpt_{uuid.uuid4().hex[:12]}"
    async with get_session() as session:
        session.add(AnalyticsReport(
            id=report_id, business_id=business_id, generated_by=generated_by,
            title=title, time_window=json.dumps(time_window or {}, ensure_ascii=False),
            html=html, rows_json=json.dumps(rows_all, ensure_ascii=False, default=str),
        ))
        await session.commit()
    return {"id": report_id, "title": title, "sections": len(sections)}


async def list_reports(business_id: str) -> list[dict]:
    async with get_session() as session:
        rows = (
            await session.execute(
                select(AnalyticsReport).where(AnalyticsReport.business_id == business_id)
                .order_by(AnalyticsReport.created_at.desc()).limit(50)
            )
        ).scalars().all()
    return [{"id": r.id, "title": r.title, "timeWindow": r.time_window,
             "generatedBy": r.generated_by,
             "createdAt": r.created_at.isoformat() if r.created_at else None} for r in rows]


async def get_report(business_id: str, report_id: str) -> dict | None:
    async with get_session() as session:
        row = (
            await session.execute(
                select(AnalyticsReport).where(
                    AnalyticsReport.business_id == business_id, AnalyticsReport.id == report_id
                )
            )
        ).scalars().first()
    if not row:
        return None
    return {"id": row.id, "title": row.title, "html": row.html, "rows": json.loads(row.rows_json)}


async def export_csv(business_id: str, report_id: str) -> str | None:
    """报告 → CSV(14-D2:表格一键导出;每指标一节)。"""
    report = await get_report(business_id, report_id)
    if not report:
        return None
    buf = io.StringIO()
    writer = csv.writer(buf)
    for metric, rows in report["rows"].items():
        writer.writerow([f"== {metric} =="])
        if rows:
            writer.writerow(rows[0])
            for r in rows:
                writer.writerow(r.values())
        writer.writerow([])
    return buf.getvalue()


async def save_result_report(business_id: str, generated_by: str, question: str,
                             metric: str, unit: str, caliber: str, rows: list[dict]) -> dict:
    """对话结果卡 → 单节报告(ADR-0005 出口:问过的就能存;我的报告页可见/可导 CSV)。

    rows_json 沿用 generate_report 的 {metric: rows} 字典形,export_csv 零改动复用;
    数字全部来自对话里真实执行的查询(14-D3 不变量),本函数只做搬运不重算。
    """
    section = {"metric": metric, "unit": unit, "caliber": caliber, "rows": rows}
    title = (question or f"{metric} 查询结果").strip()[:60] or f"{metric} 查询结果"
    report_id = f"rpt_{uuid.uuid4().hex[:12]}"
    async with get_session() as session:
        session.add(AnalyticsReport(
            id=report_id, business_id=business_id, generated_by=generated_by,
            title=title, time_window=json.dumps({"source": "agent_result"}, ensure_ascii=False),
            html=_html_report(title, [section]),
            rows_json=json.dumps({metric: rows}, ensure_ascii=False, default=str),
        ))
        await session.commit()
    return {"id": report_id, "title": title}
