"""标注水龙头互斥契约(2026-10-02 收编:三通道资格谓词与回写 SQL 单点)。

「谁有资格写 intent_logs.actual_outcome」的三通道互补谓词(①置信级联独占
confidence_cascade / ②人审不限 / ③规则复判排除 confidence_cascade)过去
活在三个文件的注释里互指,互斥从未被同一测试面钉过 —— 本册就是那个面:

- ①只认澄清行 + 30 分钟窗 + 单 thread 最近一行;
- ②不限 method 但认 IS NULL 门槛(「最近一条待回填」≠「最近一条」);
- ③排除面(cascade / 字面空文本不进扫描)+ 批量 limit + created_at DESC;
- 一次写入:任何通道对已回填行零影响,write_outcome_by_id 先到先得;
- 互斥核心:①/②贴过的行③重扫永不命中。

sqlite 密封造数(JSONB DDL 经 compiles 钩子降级,套路同
test_export_intent_data);①自管 get_session 经 monkeypatch 指向 sqlite
门面。①既有 4 例容器 DB 回归(test_intent_outcome_backfill.py)与本册
互补:那边钉 log_intent_to_db 全链路,这边钉资格谓词矩阵。
"""

from __future__ import annotations

import asyncio
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from engine_py.db.models import Base, IntentLog
from engine_py.triage import labeling


# sqlite 方言下把 JSONB DDL 降级为通用 JSON(值序列化本就复用 sqlalchemy.JSON)
@compiles(JSONB, "sqlite")
def _jsonb_sqlite(type_, compiler, **kw):
    return "JSON"


class _AsyncSessionFacade:
    """只实现 ``execute``/``commit`` 的 AsyncSession 门面:语句交给底层同步 sqlite 会话。"""

    def __init__(self, sync_session: Session) -> None:
        self._sync = sync_session

    async def execute(self, stmt):
        return self._sync.execute(stmt)

    async def commit(self) -> None:
        self._sync.commit()


@pytest.fixture()
def db_engine():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[IntentLog.__table__])
    yield engine
    engine.dispose()


@pytest.fixture()
def facade(db_engine):
    with Session(db_engine) as sync:
        yield _AsyncSessionFacade(sync)


@pytest.fixture()
def clarify_channel(db_engine, monkeypatch):
    """通道①自管 get_session → sqlite 门面(同 test_export TestMain 的注入套路)。"""

    @asynccontextmanager
    async def fake_get_session():
        with Session(db_engine) as sync:
            yield _AsyncSessionFacade(sync)

    monkeypatch.setattr(labeling, "get_session", fake_get_session)
    return db_engine


def _minutes_ago(n: int) -> datetime:
    """naive now-Δ:表内 created_at 为 DB 服务器 naive now(),与①的 cutoff 同形比较。"""
    return datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=n)


def _add(
    engine,
    thread_id: str,
    method: str | None,
    created_at: datetime,
    *,
    input_text: str = "帮我把那个东西弄一下",
    outcome: str | None = None,
) -> uuid.UUID:
    row_id = uuid.uuid4()
    with Session(engine) as session:
        session.add(
            IntentLog(
                id=row_id,
                thread_id=thread_id,
                input_text=input_text,
                predicted_intents=[{"intent": "consult", "confidence": 0.4}],
                method=method,
                confidence=0.4,
                candidates=[],
                actual_outcome=outcome,
                created_at=created_at,
            )
        )
        session.commit()
    return row_id


def _outcome_of(engine, row_id: uuid.UUID) -> str | None:
    with Session(engine) as session:
        return session.execute(select(IntentLog.actual_outcome).where(IntentLog.id == row_id)).scalar_one()


class TestChannel1ClarifyCascade:
    def test_only_cascade_rows_eligible(self, clarify_channel):
        """①只贴澄清行:同 thread 更新的 structured_llm 待回填行不配作目标。"""
        cascade = _add(clarify_channel, "t", "confidence_cascade", _minutes_ago(10))
        normal = _add(clarify_channel, "t", "structured_llm", _minutes_ago(5))

        written = asyncio.run(labeling.backfill_clarify_outcome("t", "consult"))

        assert written == 1
        assert _outcome_of(clarify_channel, cascade) == "consult"
        assert _outcome_of(clarify_channel, normal) is None, "普通终局行严禁被①污染"

    def test_thirty_minute_window(self, clarify_channel):
        """①时间资格:31 分钟前的澄清行出窗不贴,29 分钟内的在窗。"""
        stale = _add(clarify_channel, "stale", "confidence_cascade", _minutes_ago(31))
        fresh = _add(clarify_channel, "fresh", "confidence_cascade", _minutes_ago(29))

        assert asyncio.run(labeling.backfill_clarify_outcome("stale", "consult")) == 0
        assert _outcome_of(clarify_channel, stale) is None
        assert asyncio.run(labeling.backfill_clarify_outcome("fresh", "order_query")) == 1
        assert _outcome_of(clarify_channel, fresh) == "order_query"

    def test_latest_pending_row_wins(self, clarify_channel):
        """①单 thread 最近一行:多轮连续澄清只认最后一次,旧行留给下一次。"""
        older = _add(clarify_channel, "t", "confidence_cascade", _minutes_ago(20))
        newer = _add(clarify_channel, "t", "confidence_cascade", _minutes_ago(10))

        assert asyncio.run(labeling.backfill_clarify_outcome("t", "consult")) == 1
        assert _outcome_of(clarify_channel, newer) == "consult"
        assert _outcome_of(clarify_channel, older) is None

    def test_never_overwrites_filled_row(self, clarify_channel):
        """①一次写入:已回填澄清行返回 0 且值不变。"""
        filled = _add(clarify_channel, "t", "confidence_cascade", _minutes_ago(5), outcome="refund")

        assert asyncio.run(labeling.backfill_clarify_outcome("t", "consult")) == 0
        assert _outcome_of(clarify_channel, filled) == "refund"


class TestChannel2HumanReview:
    def test_any_method_but_null_gate(self, db_engine, facade):
        """②不限 method:structured_llm 行(①永不碰)可贴;「最近一条待回填」≠「最近一条」。"""
        pending = _add(db_engine, "t", "structured_llm", _minutes_ago(10))
        _add(db_engine, "t", "structured_llm", _minutes_ago(5), outcome="refund")  # 更新但已回填

        written = asyncio.run(labeling.backfill_pending_outcome(facade, "t", "consult"))

        assert written == 1
        assert _outcome_of(db_engine, pending) == "consult"

    def test_no_pending_row_is_noop(self, db_engine, facade):
        """无可回写行返回 0(调用方按此提示「标签可能已被通道①写走」)。"""
        _add(db_engine, "t", "rule", _minutes_ago(5), outcome="refund")
        assert asyncio.run(labeling.backfill_pending_outcome(facade, "t", "consult")) == 0

    def test_never_overwrites(self, db_engine, facade):
        filled = _add(db_engine, "t", "rule", _minutes_ago(5), outcome="refund")
        assert asyncio.run(labeling.backfill_pending_outcome(facade, "t", "consult")) == 0
        assert _outcome_of(db_engine, filled) == "refund"


class TestChannel3RulesBackfill:
    def test_exclusion_surface(self, db_engine, facade):
        """③排除面:cascade(待回填或已回填)与字面空文本行不进扫描;method NULL 行保留。"""
        _add(db_engine, "t", "confidence_cascade", _minutes_ago(1))
        _add(db_engine, "t", "confidence_cascade", _minutes_ago(2), outcome="refund")
        _add(db_engine, "t", "structured_llm", _minutes_ago(3), input_text="")
        rule_row = _add(db_engine, "t", "rule", _minutes_ago(4))
        null_method_row = _add(db_engine, "t", None, _minutes_ago(5))

        rows = asyncio.run(labeling.backfillable_rows(facade, limit=100))

        assert {r.id for r in rows} == {rule_row, null_method_row}, "排除面失守"

    def test_order_and_limit(self, db_engine, facade):
        """③created_at DESC + limit 截断。"""
        for i in range(3):
            _add(db_engine, f"t{i}", "rule", _minutes_ago(i + 1), input_text=f"q{i}")

        rows = asyncio.run(labeling.backfillable_rows(facade, limit=2))

        assert [r.input_text for r in rows] == ["q0", "q1"], "必须 created_at DESC 取前 limit 条"

    def test_mutual_exclusion_after_channel2(self, db_engine, facade):
        """互斥核心:②贴过的行(actual_outcome 非 NULL)③重扫永不命中。"""
        row = _add(db_engine, "t", "structured_llm", _minutes_ago(5))
        assert asyncio.run(labeling.backfill_pending_outcome(facade, "t", "consult")) == 1

        assert asyncio.run(labeling.write_outcome_by_id(facade, row, "order_query")) == 0
        remaining = asyncio.run(labeling.backfillable_rows(facade, limit=100))
        assert {r.id for r in remaining} == set(), "已回填行严禁再进③扫描"


def test_write_outcome_first_write_wins(db_engine, facade):
    """write_outcome_by_id 双保险:资格谓词选出行后、他人先写,回写 0 不覆写。"""
    row = _add(db_engine, "t", "rule", _minutes_ago(5))
    assert asyncio.run(labeling.write_outcome_by_id(facade, row, "refund")) == 1
    assert asyncio.run(labeling.write_outcome_by_id(facade, row, "consult")) == 0
    assert _outcome_of(db_engine, row) == "refund"
