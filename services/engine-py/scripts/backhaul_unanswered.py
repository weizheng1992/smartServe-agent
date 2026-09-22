"""未命中问句回捞(增长飞轮闭环;ADR-0005):历史 agent_unanswered 逐条重试当前管线。

闭集/模板/词面每批演进后跑一次:当年答不上的问句,今天可能已经可答。
四分类:
- answerable  : 现管线可答 —— L3 命中时已自动沉淀 L2 范例,同义问法此后免费;
- need_entity : 需指认实体(clarify;用户补实体后即可答);
- out_of_scope: 问因/闲聊等设计外 —— 诚实 unsupported 是正确行为,本清单按频次
                排序就是下一批意图登记的输入;
- error       : 执行异常(需排查,非语义问题)。

用法(services/engine-py 下):
  uv run python scripts/backhaul_unanswered.py --business aurora [--role finance_owner] [--limit 50]
"""

from __future__ import annotations

import argparse
import asyncio

from sqlalchemy import func, select

from engine_py.analytics.graph import ask
from engine_py.db import AgentUnanswered, get_session


async def backhaul(business_id: str, role: str, limit: int) -> dict[str, list]:
    async with get_session() as session:
        rows = (
            await session.execute(
                select(AgentUnanswered.question, func.count().label("n"))
                .where(AgentUnanswered.business_id == business_id)
                .group_by(AgentUnanswered.question)
                .order_by(func.count().desc())
                .limit(limit)
            )
        ).all()

    buckets: dict[str, list] = {"answerable": [], "need_entity": [], "out_of_scope": [], "error": []}
    for question, n in rows:
        try:
            outcome = await ask(question, {"business_id": business_id, "role": role})
        except Exception as err:
            buckets["error"].append((question, n, str(err)[:60]))
            continue
        kind = outcome.get("type")
        if kind == "result":
            buckets["answerable"].append((question, n, str(outcome.get("metric", ""))))
        elif kind == "clarify":
            buckets["need_entity"].append((question, n, str(outcome.get("question", ""))[:40]))
        else:  # unsupported
            buckets["out_of_scope"].append((question, n, str(outcome.get("message", ""))[:40]))
    return buckets


def main() -> None:
    parser = argparse.ArgumentParser(description="未命中问句回捞报告")
    parser.add_argument("--business", default="aurora")
    parser.add_argument("--role", default="finance_owner", help="以该角色视角重试(权限面随角色)")
    parser.add_argument("--limit", type=int, default=50)
    args = parser.parse_args()

    buckets = asyncio.run(backhaul(args.business, args.role, args.limit))
    print(f"\n== 未命中回捞报告(business={args.business}, role={args.role})==")
    for kind, items in buckets.items():
        print(f"\n[{kind}] {len(items)} 条")
        for question, n, detail in items:
            print(f"  ×{n}  {question[:36]}  → {detail}")
    print(
        "\n说明:answerable 的问法 L3 已自动沉淀 L2 范例(同义问法此后免费);"
        "\nout_of_scope 按频次排序 = 下一批意图登记的优先级输入。"
    )


if __name__ == "__main__":
    main()
