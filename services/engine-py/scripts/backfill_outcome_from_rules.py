"""P2 通道③ —— 历史问句确定性复判,批量回填 actual_outcome silver label。

对 actual_outcome 为空的历史 intent_logs 行,用 SlotExtractor 词面规则
(L0,零 LLM,与 run_intent_eval 同纪律)复判:恰好一条规则高置信命中才
写标签;多规则歧义/零命中/低置信跳过 —— 歧义句留给通道①(澄清自动
回填)与通道②(人审 label),严禁硬贴。

用法(services/engine-py 下)::

    uv run python scripts/backfill_outcome_from_rules.py --dry-run     # 只看分布
    uv run python scripts/backfill_outcome_from_rules.py --limit 2000  # 实际回填

安全:单规则才贴(歧义跳过);跳过行下次运行自然重试(仍 NULL);影
响行数与分布打到 stdout。跑完接 run_intent_eval 语义不冲突 —— 本脚本
只写 actual_outcome,不动 winner/method。
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from sqlalchemy import text

from engine_py.db import get_session
from engine_py.triage.slot_extractor import SlotExtractor

# 澄清行是「判定层都拿不准」的句子,其标签走通道①(用户后续选择);
# 在此复判等于给歧义句硬贴 —— 严禁。
_EXCLUDED_METHODS = ("confidence_cascade",)


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--limit", type=int, default=2000, help="单批最多处理行数")
    parser.add_argument("--dry-run", action="store_true", help="只打印分布,不写库")
    args = parser.parse_args()

    async with get_session() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT id, input_text, method FROM intent_logs "
                    "WHERE actual_outcome IS NULL AND COALESCE(input_text, '') <> '' "
                    "AND (method IS NULL OR method <> ALL(:excluded)) "
                    "ORDER BY created_at DESC LIMIT :limit"
                ).bindparams(excluded=list(_EXCLUDED_METHODS), limit=args.limit)
            )
        ).all()

    labeled: list[tuple[str, str]] = []  # (id, silver)
    skipped_multi = skipped_none = skipped_lowconf = 0
    for row_id, input_text, _method in rows:
        silver = SlotExtractor.pick_silver_label(input_text)
        if silver is None:
            detected = SlotExtractor.detect_intents(input_text)
            if len(detected) > 1:
                skipped_multi += 1
            elif detected:
                skipped_lowconf += 1
            else:
                skipped_none += 1
            continue
        labeled.append((row_id, silver))

    dist = Counter(silver for _, silver in labeled)
    print(f"扫描 {len(rows)} 行待回填:可贴 {len(labeled)} | 多规则歧义跳过 {skipped_multi} "
          f"| 零命中 {skipped_none} | 低置信 {skipped_lowconf}")
    print("按意图分布:", dict(dist))

    if args.dry_run:
        print("(dry-run,未写库)")
        return 0

    written = 0
    async with get_session() as session:
        for row_id, silver in labeled:
            result = await session.execute(
                text("UPDATE intent_logs SET actual_outcome = :s WHERE id = :i").bindparams(
                    s=silver, i=row_id)
            )
            written += result.rowcount or 0
        await session.commit()
    print(f"回填完成: {written} 行")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
