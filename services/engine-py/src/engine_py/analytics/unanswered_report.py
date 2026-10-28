"""unanswered 周报(grill 2026-10-26 Q3③ SOP 落地):`agent_unanswered` 近 N 天
聚合 —— 高频未命中问句就是词表/指标闭集/组合面的进料口。

用法(dev/运维,只读直查):
    cd services/engine-py && uv run python -m engine_py.analytics.unanswered_report
    uv run python -m engine_py.analytics.unanswered_report --days 7 --top 20

SOP 节奏(建议周级):跑本报告 → 按 hint 粗分类分派 →
- 同义词条缺失(问法新、指标旧)→ metrics.yaml synonyms 补录
- 指标闭集外(复购率式)→ metrics.yaml 新指标票(compile 块声明式)
- 时间词未识别 → TIME_PATTERNS/unparsed_time_hint 评估
- 域外/闲聊 → 维持 unsupported(正确行为,无需动作)
"""

from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from ..db import get_session

# 词表单点派生(评审收口:本地第三份词表与主表漂移——归因桶直用
# composition.REASON_RE,时间桶直用 l0.unparsed_time_hint 只圈**不可解析**
# 时间词,可解析词命中的问句该走别的桶而非时间补录)
from .composition import REASON_RE
from .l0_lexicon import unparsed_time_hint


def _classify(q: str) -> str:
    if REASON_RE.search(q):
        return "归因问句"
    if unparsed_time_hint(q):
        return "含不可解析时间词"
    return "其他(评估词表/闭集)"


async def _report(days: int, top: int) -> None:
    # created_at 为 naive UTC(server_default now() 同源),比对钟同口径
    since = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=days)
    async with get_session() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT question, role, created_at FROM agent_unanswered "
                    "WHERE created_at >= :since ORDER BY created_at DESC"
                ),
                {"since": since},
            )
        ).fetchall()
    if not rows:
        print(f"近 {days} 天 agent_unanswered 为空(闭集覆盖良好或流量为零)")
        return

    norm = Counter()
    for r in rows:
        norm[(r.question or "").strip().rstrip("?？").lower()] += 1
    roles = Counter(r.role for r in rows)
    buckets = Counter(_classify(r.question or "") for r in rows)

    print(f"=== agent_unanswered 近 {days} 天: {len(rows)} 条 / 去重 {len(norm)} 个问句 ===")
    print("按角色:", dict(roles.most_common()))
    print("按粗分类:", dict(buckets.most_common()))
    print(f"\nTOP {top} 高频问句(频次 | 分类 | 问句):")
    for q, n in norm.most_common(top):
        print(f"  {n:>3} | {_classify(q):<10} | {q[:60]}")


def main() -> None:
    ap = argparse.ArgumentParser(description="agent_unanswered 周报(只读)")
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--top", type=int, default=20)
    args = ap.parse_args()
    asyncio.run(_report(args.days, args.top))


if __name__ == "__main__":
    main()
