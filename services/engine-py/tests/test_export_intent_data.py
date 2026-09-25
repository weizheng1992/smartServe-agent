"""意图数据导出 CLI(07 最小数据水龙头)。

scripts/export_intent_data.py 不在 engine_py 包内,经 importlib 按路径加载;
DB 侧用内存 sqlite 建三张目标表造数(不依赖真实 postgres):JSONB 的 DDL
在 sqlite 方言下经 ``compiles`` 钩子降级为 JSON,server_default(now()/
gen_random_uuid())不适用 sqlite → 造数时显式给全 id/created_at/updated_at。
时间窗/排序走真实 SQL 过滤,async 路径用只实现 ``execute`` 的同步会话门面。
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from engine_py.db.models import BadcaseCandidate, Base, IntentLog, LowConfidenceLog


# sqlite 方言下把 JSONB DDL 降级为通用 JSON(值序列化本就复用 sqlalchemy.JSON)
@compiles(JSONB, "sqlite")
def _jsonb_sqlite(type_, compiler, **kw):
    return "JSON"


def _naive(*args: int) -> datetime:
    """构造 naive datetime:表内 created_at 是 DB 服务器 naive now(),造数与断言必须同形。"""
    return datetime(*args)  # noqa: DTZ001


# 按路径加载 scripts/ 下的 CLI(非包成员,无法常规 import)
_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "export_intent_data.py"
_spec = importlib.util.spec_from_file_location("export_intent_data", _SCRIPT_PATH)
assert _spec is not None and _spec.loader is not None
export_intent_data = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(export_intent_data)


@pytest.fixture(autouse=True)
def _restore_env_after_main():
    """main() 会经 _load_env_file 把 .env(含仓库根)全量 setdefault 进 os.environ
    且脚本侧不清理 —— CLI 短进程无害,测试长进程则是跨文件污染:曾把
    AI_RESULT_CACHE_TTL=60 泄漏给后续 analytics 测试,令其命中 Redis 陈旧缓存
    假红(2026-09-26 夜审定位)。逐测快照恢复,进程出测试时环境原样。"""
    snapshot = dict(os.environ)
    yield
    os.environ.clear()
    os.environ.update(snapshot)


class _AsyncSessionFacade:
    """只实现 ``execute`` 的 AsyncSession 门面:把语句交给底层同步 sqlite 会话。"""

    def __init__(self, sync_session: Session) -> None:
        self._sync = sync_session

    async def execute(self, stmt):
        return self._sync.execute(stmt)


@pytest.fixture()
def db_engine():
    """内存 sqlite:只建三张目标表并铺固定时间点的种子行(FK 指向不存在的 threads 无碍,PRAGMA 默认关)。"""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[IntentLog.__table__, LowConfidenceLog.__table__, BadcaseCandidate.__table__],
    )
    with Session(engine) as session:
        session.add_all(
            [
                IntentLog(
                    id=uuid.uuid4(),
                    thread_id="t1",
                    input_text="我的订单到哪了",
                    predicted_intents=[{"intent": "order_status", "confidence": 0.9, "type": "primary"}],
                    method="embedding",
                    confidence=0.9,
                    winner="order_status",
                    candidates=[{"layer": "embedding", "intent": "order_status", "confidence": 0.9}],
                    arbitration_reason="embedding_order_status",
                    created_at=_naive(2026, 9, 1, 10, 0, 0),
                ),
                IntentLog(
                    id=uuid.uuid4(),
                    thread_id="t2",
                    input_text="这个能退吗",
                    predicted_intents=[{"intent": "refund", "confidence": 0.3, "type": "primary"}],
                    method="rule",
                    confidence=0.3,
                    winner=None,  # 真实写入方 intents 为空时 winner=None,测回落
                    created_at=_naive(2026, 9, 5, 10, 0, 0),
                ),
                LowConfidenceLog(
                    id=uuid.uuid4(),
                    thread_id="t2",
                    input_text="这个能退吗",
                    candidates=[{"intent": "refund", "confidence": 0.3, "type": "primary"}],
                    reviewed=False,
                    created_at=_naive(2026, 9, 5, 10, 0, 0),
                ),
                LowConfidenceLog(
                    id=uuid.uuid4(),
                    thread_id="t3",
                    input_text="嗯哼",
                    candidates=None,  # 边界:无候选可推导
                    reviewed=True,
                    created_at=_naive(2026, 9, 7, 9, 0, 0),
                ),
                BadcaseCandidate(
                    id=uuid.uuid4(),
                    signal_source="intent_conflict",
                    conversation_ref="thread:t1",
                    business_id="ecommerce",
                    suggested_class="neutral",
                    status="candidate",
                    note="slot_extractor=refund@0.95 vs structured_llm=consult@0.9",
                    created_at=_naive(2026, 9, 6, 8, 0, 0),
                    updated_at=_naive(2026, 9, 6, 8, 0, 0),
                ),
            ]
        )
        session.commit()
    yield engine
    engine.dispose()


def _intent_row(engine, thread_id: str) -> IntentLog:
    with Session(engine) as session:
        return session.execute(select(IntentLog).where(IntentLog.thread_id == thread_id)).scalar_one()


def _low_conf_row(engine, thread_id: str) -> LowConfidenceLog:
    with Session(engine) as session:
        return (
            session.execute(select(LowConfidenceLog).where(LowConfidenceLog.thread_id == thread_id)).scalar_one()
        )


def _badcase_row(engine) -> BadcaseCandidate:
    with Session(engine) as session:
        return session.execute(select(BadcaseCandidate)).scalar_one()


class TestRowToRecord:
    def test_intent_record_full_fields(self, db_engine):
        """intent 源:五要素齐全 + 仲裁留痕透传。"""
        record = export_intent_data.row_to_record(
            "intent", _intent_row(db_engine, "t1")
        )
        assert record["source"] == "intent"
        assert record["query"] == "我的订单到哪了"
        assert record["intent"] == "order_status"
        assert record["confidence"] == 0.9
        assert record["source_stage"] == "embedding"
        assert record["created_at"] == "2026-09-01T10:00:00"
        assert record["thread_id"] == "t1"
        assert record["candidates"][0]["layer"] == "embedding"
        assert record["arbitration_reason"] == "embedding_order_status"

    def test_intent_winner_missing_falls_back(self, db_engine):
        """winner 为空时回落 predicted_intents[0].intent。"""
        record = export_intent_data.row_to_record(
            "intent", _intent_row(db_engine, "t2")
        )
        assert record["intent"] == "refund"

    def test_low_confidence_derived_from_candidates(self, db_engine):
        """low_confidence 源:表内无 intent/confidence/method 列,自 candidates[0] 推导;source_stage 恒空。"""
        record = export_intent_data.row_to_record(
            "low_confidence", _low_conf_row(db_engine, "t2")
        )
        assert record["query"] == "这个能退吗"
        assert record["intent"] == "refund"
        assert record["confidence"] == 0.3
        assert record["source_stage"] is None
        assert record["reviewed"] is False

    def test_low_confidence_without_candidates(self, db_engine):
        """无候选行:intent/confidence 保持 null,不炸。"""
        record = export_intent_data.row_to_record(
            "low_confidence", _low_conf_row(db_engine, "t3")
        )
        assert record["intent"] is None
        assert record["confidence"] is None

    def test_badcase_is_pointer_only(self, db_engine):
        """badcase 源:零原始数据红线 —— query/intent/confidence 恒空,信号源与会话引用齐全。"""
        record = export_intent_data.row_to_record("badcase", _badcase_row(db_engine))
        assert record["query"] is None
        assert record["intent"] is None
        assert record["confidence"] is None
        assert record["source_stage"] == "intent_conflict"
        assert record["conversation_ref"] == "thread:t1"
        assert record["business_id"] == "ecommerce"
        assert record["status"] == "candidate"


class TestCollectRecords:
    def test_time_window_filters_and_orders(self, db_engine):
        """窗口含端点、created_at 升序:09-01 行被 since 排除,09-05 行保留。"""
        with Session(db_engine) as sync:

            async def run():
                return await export_intent_data.collect_records(
                    _AsyncSessionFacade(sync),
                    "intent",
                    _naive(2026, 9, 2, 0, 0, 0),
                    _naive(2026, 9, 5, 23, 59, 59),
                )

            records = asyncio.run(run())
        assert [r["query"] for r in records] == ["这个能退吗"]

    def test_low_confidence_and_badcase_windows(self, db_engine):
        """同规则覆盖另两张表:窗口外为空、窗口内命中。"""
        with Session(db_engine) as sync:

            async def run(source, since, until):
                return await export_intent_data.collect_records(
                    _AsyncSessionFacade(sync), source, since, until
                )

            empty = asyncio.run(
                run("badcase", _naive(2026, 9, 2), _naive(2026, 9, 5, 23, 59, 59))
            )
            hit = asyncio.run(run("badcase", _naive(2026, 9, 6), None))
            late_lc = asyncio.run(run("low_confidence", _naive(2026, 9, 6), None))
        assert empty == []
        assert [r["source_stage"] for r in hit] == ["intent_conflict"]
        assert [r["query"] for r in late_lc] == ["嗯哼"]

    def test_no_window_returns_all_ascending(self, db_engine):
        with Session(db_engine) as sync:
            records = asyncio.run(
                export_intent_data.collect_records(_AsyncSessionFacade(sync), "intent", None, None)
            )
        assert [r["created_at"] for r in records] == [
            "2026-09-01T10:00:00",
            "2026-09-05T10:00:00",
        ]


class TestWriteJsonl:
    def test_write_to_file(self, tmp_path):
        records = [
            {"source": "intent", "query": "q1", "intent": "order_status"},
            {"source": "intent", "query": "q2", "intent": None},
        ]
        out = tmp_path / "sub" / "out.jsonl"
        export_intent_data.write_jsonl(records, str(out))
        lines = out.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 2
        assert json.loads(lines[0])["query"] == "q1"
        assert out.read_text(encoding="utf-8").endswith("}\n")

    def test_write_to_stdout(self, capsys):
        export_intent_data.write_jsonl([{"source": "badcase", "id": "x"}], None)
        assert json.loads(capsys.readouterr().out)["id"] == "x"


class TestParseTs:
    def test_date_only_means_midnight(self):
        assert export_intent_data.parse_ts("2026-09-01", "since") == _naive(2026, 9, 1)

    def test_tz_normalized_to_utc_naive(self):
        assert export_intent_data.parse_ts("2026-09-01T08:00:00+08:00", "until") == _naive(
            2026, 9, 1, 0, 0, 0
        )

    def test_invalid_raises_system_exit(self):
        with pytest.raises(SystemExit):
            export_intent_data.parse_ts("not-a-date", "since")


class TestMain:
    def test_end_to_end_with_fake_session(self, tmp_path, monkeypatch, db_engine):
        """CLI 全链路:换掉 get_session 指向 sqlite 门面,--out 落文件。"""

        @asynccontextmanager
        async def fake_get_session():
            with Session(db_engine) as sync:
                yield _AsyncSessionFacade(sync)

        monkeypatch.setattr(export_intent_data, "get_session", fake_get_session)
        out = tmp_path / "lc.jsonl"
        count = export_intent_data.main(
            ["--source", "low_confidence", "--since", "2026-09-04", "--out", str(out)]
        )
        assert count == 2  # 09-05(refund)与 09-07(无候选)两行均在窗内
        lines = out.read_text(encoding="utf-8").splitlines()
        first = json.loads(lines[0])
        assert first["source"] == "low_confidence"
        assert first["intent"] == "refund"
        assert first["confidence"] == 0.3
        assert json.loads(lines[1])["intent"] is None

    def test_stdout_mode_returns_count(self, capsys, monkeypatch, db_engine):
        @asynccontextmanager
        async def fake_get_session():
            with Session(db_engine) as sync:
                yield _AsyncSessionFacade(sync)

        monkeypatch.setattr(export_intent_data, "get_session", fake_get_session)
        count = export_intent_data.main(["--source", "intent", "--until", "2026-09-02", "--out", "-"])
        assert count == 1
        stdout = capsys.readouterr().out
        assert json.loads(stdout.splitlines()[0])["query"] == "我的订单到哪了"
