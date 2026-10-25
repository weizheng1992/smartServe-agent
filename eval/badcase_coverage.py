#!/usr/bin/env python3
"""坏例类型 × 套件覆盖对照表(eval-gap-2026-10 08 号票:offline 代表性量化)。

读 badcase_candidates(缺省近 90 天)按信号源族聚合,对照静态覆盖映射输出
「池内体量 / 已覆盖面 / 状态」矩阵 —— 每月跑一次,缺口族进月度回灌议程:

  1. digest 摘选取 top 族 → 人工 triage → 脱敏后并入对应分册 testCases
     (origin: badcase:{id} 溯源),同 PR 重钉基线,changelog 记「与旧基线不可比」;
  2. 👍 正向信号:Data Agent 臂已自动注册 user 范例回灌 L2(v3.1);
  3. chat 臂反馈 UI(apps/web)在禁区,正向采样暂缺 —— 缺口常驻本表。

用法(仓库根,需 .env):
    python3 eval/badcase_coverage.py [--days 90]
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
from collections import Counter

# 信号源族 → 覆盖面(静态映射:改套件时同步维护)
COVERAGE = {
    "intent_conflict": ("意图差分对拍(Gen-3 intent_cases 572 例)+ unified intentF1 册", "covered"),
    "nightly_agent_eval": ("夜评自身失败 → baseline-incidents 回归册通道(转正后同 PR 重钉)", "covered"),
    "approval_rejected": ("c36 reject 诚实回复(夜评严判)", "covered"),
    "circuit_breaker": ("夜评熔断即红场景族 + session_metrics resolution_status 遥测", "covered"),
    "persona_fact_deleted": ("persona 册(scope 双层/置信档位)", "covered"),
    "thumbs_down": ("Data Agent 臂:👍 自动注册 user 范例回灌 L2(v3.1);👎 本池候选", "auto-loop"),
    "thumbs_up": ("Data Agent 臂自动回灌 L2(撤判补偿),无需人工", "auto-loop"),
    "human_takeover": ("c33 转人工排队(夜评)+ live_desk 面(P5 搁置)", "partial"),
    "intent_mismatch": ("unified intentF1 册(宣称 out_of_scope × 落库不符族)", "covered"),
    "claim_mismatch": ("全局编造检查(夜评)+ data 册 unsupported 负例", "covered"),
    "chat_feedback": ("chat 臂无反馈 UI(apps/web 禁区)—— 正向采样缺口常驻", "gap"),
}


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=90)
    args = ap.parse_args()

    env = {}
    for line in open(".env", encoding="utf-8"):
        m = re.match(r"^([A-Z_]+)=(.*)$", line.strip())
        if m:
            env[m.group(1)] = m.group(2)

    import asyncpg

    conn = await asyncpg.connect(env["DATABASE_URL"].replace("+asyncpg", ""))
    rows = await conn.fetch(
        "SELECT signal_source, count(*) AS n FROM badcase_candidates "
        "WHERE created_at > now() - ($1 || ' days')::interval GROUP BY 1 ORDER BY 2 DESC",
        str(args.days),
    )
    await conn.close()

    pool = Counter({r["signal_source"]: r["n"] for r in rows})
    print(f"\n坏例池(近 {args.days} 天)× 套件覆盖对照 — {len(pool)} 信号源族\n")
    print(f"{'信号源':<22}{'池内':>6}  {'覆盖面':<52}状态")
    print("-" * 100)
    for source, n in pool.most_common():
        face, status = COVERAGE.get(source, ("未登记族 —— 月度评审定去向", "NEW"))
        tag = {"covered": "✅ 已覆盖", "auto-loop": "🔄 自动回灌", "partial": "◐ 部分", "gap": "❌ 缺口"}.get(status, "🆕 新族")
        print(f"{source:<22}{n:>6}  {face:<50}{tag}")
    for source, (face, status) in COVERAGE.items():
        if source not in pool and status == "gap":
            print(f"{source:<22}{0:>6}  {face:<50}❌ 缺口(结构性,待禁区解封)")
    print(
        "\n月度回灌流程:digest top 族 → 人工 triage(零原始数据原则)→ 脱敏并入分册"
        "(origin: badcase:{id})→ 同 PR 重钉基线 + changelog 记不可比。\n"
    )


if __name__ == "__main__":
    asyncio.run(main())
