"""意图数据导出 CLI — 最小数据水龙头(07 落码票,2026-09-17)。

按时间窗把三张积累表导出为 JSONL,供 06 号票(数据规模盘点)与后续标注/
评测消费;只读导出,不改任何写入语义、不建标注界面、不建训练管线:

- ``--source intent``         → intent_logs(终局意图判定,含仲裁留痕)
- ``--source low_confidence`` → low_confidence_logs(intent 落库后 confidence<0.65 的子集)
- ``--source badcase``        → badcase_candidates(坏例候选池)

字段口径(每行至少 query / intent / confidence / source_stage / created_at):
- intent:query=input_text,intent=winner(缺则回落 predicted_intents[0]),
  confidence=confidence 列,source_stage=method(终局判定层);
- low_confidence:表内无 confidence/intent/method 列 —— intent 与 confidence 从
  candidates[0](写入方传入的终局 intents 列表)推导,source_stage 恒为 null;
- badcase:候选池只存信号引用不存原文(仓库零原始数据红线),query/intent/
  confidence 恒为 null,source_stage=signal_source,原文定位走 conversation_ref。

用法(在 ``services/engine-py`` 下执行)::

    uv run python scripts/export_intent_data.py --source intent \
        --since 2026-09-01 --until 2026-09-17T23:59:59 --out /tmp/intent.jsonl
    uv run python scripts/export_intent_data.py --source badcase            # stdout

``--since/--until`` 接受 ISO 日期或日期时间(均含端点);带时区视为 UTC 后
取整为 naive(表内 created_at 为 DB 服务器 now() 的 naive 时间)。缺省全量,
输出按 created_at 升序;行数摘要打到 stderr,stdout 始终是纯 JSONL。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select

from engine_py.db import BadcaseCandidate, IntentLog, LowConfidenceLog, get_session

SOURCE_INTENT = "intent"
SOURCE_LOW_CONFIDENCE = "low_confidence"
SOURCE_BADCASE = "badcase"
SOURCES = (SOURCE_INTENT, SOURCE_LOW_CONFIDENCE, SOURCE_BADCASE)

_SOURCE_MODELS: dict[str, type] = {
    SOURCE_INTENT: IntentLog,
    SOURCE_LOW_CONFIDENCE: LowConfidenceLog,
    SOURCE_BADCASE: BadcaseCandidate,
}


def parse_ts(value: str, arg_name: str) -> datetime:
    """ISO 日期/日期时间 → naive datetime;带时区视为 UTC 后去 tz(对齐表内 naive now())。"""
    text = value.strip()
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as err:
        raise SystemExit(f"[Export] --{arg_name} 不是合法 ISO 日期/日期时间: {value}({err})") from err
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(UTC).replace(tzinfo=None)
    return parsed


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _first_entry(value: Any) -> dict:
    """取首个 dict 形条目:low_confidence_logs.candidates 实存写入方传入的终局 intents 列表。"""
    if isinstance(value, list):
        return next((entry for entry in value if isinstance(entry, dict)), {})
    return {}


def row_to_record(source: str, row: Any) -> dict:
    """ORM 行 → JSONL 记录(纯映射;三个模型行均有 id/created_at)。"""
    record: dict[str, Any] = {
        "source": source,
        "query": None,
        "intent": None,
        "confidence": None,
        "source_stage": None,
        "created_at": _iso(row.created_at),
        "id": str(row.id),
    }
    if source == SOURCE_INTENT:
        intents = row.predicted_intents if isinstance(row.predicted_intents, list) else []
        first = intents[0] if intents and isinstance(intents[0], dict) else {}
        record.update(
            query=row.input_text,
            intent=row.winner or first.get("intent"),
            confidence=row.confidence,
            source_stage=row.method,
            thread_id=row.thread_id,
            predicted_intents=row.predicted_intents,
            candidates=row.candidates,
            arbitration_reason=row.arbitration_reason,
            actual_outcome=row.actual_outcome,
        )
    elif source == SOURCE_LOW_CONFIDENCE:
        first = _first_entry(row.candidates)
        record.update(
            query=row.input_text,
            intent=first.get("intent"),
            confidence=first.get("confidence"),
            thread_id=row.thread_id,
            reviewed=row.reviewed,
            candidates=row.candidates,
        )
    else:
        record.update(
            source_stage=row.signal_source,
            business_id=row.business_id,
            conversation_ref=row.conversation_ref,
            status=row.status,
            suggested_class=row.suggested_class,
            note=row.note,
        )
    return record


def build_stmt(source: str, since: datetime | None, until: datetime | None):
    """时间窗查询(created_at 升序;since/until 均含端点,naive 比较)。"""
    model = _SOURCE_MODELS[source]
    stmt = select(model)
    if since is not None:
        stmt = stmt.where(model.created_at >= since)
    if until is not None:
        stmt = stmt.where(model.created_at <= until)
    return stmt.order_by(model.created_at)


async def collect_records(
    session: Any, source: str, since: datetime | None, until: datetime | None
) -> list[dict]:
    """取行并映射。session 只要求具备 AsyncSession 形状的 ``execute``(便于测试注入)。"""
    rows = (await session.execute(build_stmt(source, since, until))).scalars().all()
    return [row_to_record(source, row) for row in rows]


def write_jsonl(records: list[dict], out: str | None) -> None:
    """写 JSONL:``out`` 为空或 '-' 打到 stdout,否则写文件(父目录自动创建)。"""
    lines = [json.dumps(record, ensure_ascii=False, default=str) for record in records]
    if out and out != "-":
        path = Path(out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(f"{line}\n" for line in lines), encoding="utf-8")
    else:
        for line in lines:
            print(line)


def _load_env_file() -> None:
    """轻量 .env 加载(与 badcase.cli 同策略:setdefault 不覆盖已有环境变量)。"""
    # parents[1] = services/engine-py,parents[3] = 仓库根
    here = Path(__file__).resolve()
    for env_path in (Path.cwd() / ".env", here.parents[1] / ".env", here.parents[3] / ".env"):
        if env_path.is_file():
            for line in env_path.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, value = line.partition("=")
                    os.environ.setdefault(key.strip(), value.strip().strip("'\""))
            break


async def _run(args: argparse.Namespace) -> int:
    since = parse_ts(args.since, "since") if args.since else None
    until = parse_ts(args.until, "until") if args.until else None
    async with get_session() as session:
        records = await collect_records(session, args.source, since, until)
    write_jsonl(records, args.out)
    window = f"since={args.since or '-'} until={args.until or '-'}"
    print(f"[Export] source={args.source} {window} 共 {len(records)} 条 → {args.out or 'stdout'}", file=sys.stderr)
    return len(records)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="export_intent_data.py",
        description="意图数据水龙头:按时间窗导出 intent_logs / low_confidence_logs / badcase_candidates 为 JSONL",
    )
    parser.add_argument("--source", required=True, choices=SOURCES, help="导出哪张表")
    parser.add_argument("--since", help="时间窗起点(ISO 日期或日期时间,含端点;缺省不限)")
    parser.add_argument("--until", help="时间窗终点(ISO 日期或日期时间,含端点;缺省不限)")
    parser.add_argument("--out", help="输出 JSONL 路径;缺省或 '-' 打到 stdout")
    return parser


def main(argv: list[str] | None = None) -> int:
    _load_env_file()
    args = _build_parser().parse_args(argv)
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
