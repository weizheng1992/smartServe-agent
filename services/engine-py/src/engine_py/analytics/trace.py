"""数据 agent 全链路追踪(一次问答一行)。

补最薄的日志面:此前管线每步只有 stdout print,重启即丢、无法回查。
结构化落库 analytics_trace(trace_id 串联),覆盖 L0/L2/L3/会话/场景包各层、
最终意图与模板、耗时、行数、缓存命中、结果类型。幂等建表,坏库静默
(追踪是观测面,不能反噬主流程 —— 主查询失败自有 error 帧响亮)。
"""

from __future__ import annotations

import json
import time
import uuid

from sqlalchemy import text

from ..db import get_session

_DDL = """
CREATE TABLE IF NOT EXISTS analytics_trace (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id TEXT NOT NULL,
  role TEXT NOT NULL DEFAULT 'finance_owner',
  trace_id TEXT NOT NULL,
  question TEXT NOT NULL,
  layers JSONB,
  final_metric TEXT,
  final_method TEXT,
  sql_template TEXT,
  row_count INTEGER,
  cache_hit BOOLEAN NOT NULL DEFAULT false,
  duration_ms INTEGER,
  outcome TEXT NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_analytics_trace_bid ON analytics_trace(business_id);
CREATE INDEX IF NOT EXISTS ix_analytics_trace_tid ON analytics_trace(trace_id);
"""

_ready = False


async def _ensure_table() -> None:
    global _ready
    if _ready:
        return
    from ..db import get_session as _gs

    async with _gs() as session:
        for stmt in _DDL.split(";"):
            if stmt.strip():
                await session.execute(text(stmt))
    await session.commit()
    _ready = True


def new_trace_id() -> str:
    return f"tr_{uuid.uuid4().hex[:12]}"


class Trace:
    """一次问答的追踪收集器:各层随手 append,结束时 record 落库。"""

    def __init__(self, business_id: str, role: str, question: str) -> None:
        self.business_id = business_id
        self.role = role
        self.question = question
        self.trace_id = new_trace_id()
        self.layers: list[dict] = []
        self.method = ""
        self.started = time.perf_counter()

    def add_layer(self, layer: str, **detail) -> None:
        self.layers.append({"layer": layer, **detail})

    async def record(
        self,
        outcome: str,
        final_metric: str | None = None,
        final_method: str | None = None,
        sql_template: str | None = None,
        row_count: int | None = None,
        cache_hit: bool = False,
    ) -> None:
        duration_ms = int((time.perf_counter() - self.started) * 1000)
        row = {
            "business_id": self.business_id,
            "role": self.role,
            "trace_id": self.trace_id,
            "question": self.question[:200],
            "layers": json.dumps(self.layers, ensure_ascii=False, default=str),
            "final_metric": final_metric,
            "final_method": final_method or self.method,
            "sql_template": sql_template,
            "row_count": row_count,
            "cache_hit": cache_hit,
            "duration_ms": duration_ms,
            "outcome": outcome,
        }
        try:
            await _ensure_table()
            async with get_session() as session:
                cols = ", ".join(row)
                binds = ", ".join(f":{k}" for k in row)
                await session.execute(
                    text(f"INSERT INTO analytics_trace ({cols}) VALUES ({binds})"), row,
                )
                await session.commit()
        except Exception as err:
            print(f"[Trace] 落库失败(观测面不反噬主流程): {err}")
