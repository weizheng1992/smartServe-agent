"""P2 通道③ —— 历史问句确定性复判,批量回填 actual_outcome silver label。

对 actual_outcome 为空的历史 intent_logs 行,用 SlotExtractor 词面规则
(L0,零 LLM,与 run_intent_eval 同纪律)复判:恰好一条规则高置信命中才
写标签;多规则歧义/零命中/低置信跳过 —— 歧义句留给通道①(澄清自动
回填)与通道②(人审 label),严禁硬贴。资格谓词与回写走标注水龙头
(triage/labeling.py,排除 confidence_cascade 的唯一事实点)。

用法(services/engine-py 下)::

    uv run python -m engine_py.intent_flywheel.backfill_outcome_from_rules --dry-run     # 只看分布
    uv run python -m engine_py.intent_flywheel.backfill_outcome_from_rules --limit 2000  # 实际回填

安全:单规则才贴(歧义跳过);跳过行下次运行自然重试(仍 NULL);影
响行数与分布打到 stdout。跑完接 run_intent_eval 语义不冲突 —— 本脚本
只写 actual_outcome,不动 winner/method。
"""

from __future__ import annotations

import argparse
import asyncio
from collections import Counter

from engine_py.db import get_session
from engine_py.triage import labeling
from engine_py.triage.slot_extractor import SlotExtractor


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--limit", type=int, default=2000, help="单批最多处理行数")
    parser.add_argument("--dry-run", action="store_true", help="只打印分布,不写库")
    args = parser.parse_args()

    async with get_session() as session:
        rows = await labeling.backfillable_rows(session, limit=args.limit)

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
            written += await labeling.write_outcome_by_id(session, row_id, silver)
        await session.commit()
    print(f"回填完成: {written} 行")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
