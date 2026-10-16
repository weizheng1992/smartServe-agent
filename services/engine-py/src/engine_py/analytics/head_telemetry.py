"""分类头缝②服务期遥测(shadow 分歧 / on 接管的聚合计数,补「只记 stdout」缺口)。

背景(2026-10-16 审计):l0_lexicon 的 shadow 分歧与 on 接管此前只有逐条
stdout print,重启即丢、无法回查;文档声称的「影子跑看分歧率达标再切 on」
没有数据底盘。本模块三段式:

1. record_event —— 进程内线程安全 recorder(resolve 经 asyncio.to_thread 并发
   调用是常态):单 lock 内计数 + 挂单次判定载荷;同步零 IO、永不抛
   (观测面不炸 L0 主流程)。事件闭集 EVENTS;一致事件只计数不打 print
   (分歧率 = 分歧/(分歧+一致) 需要分母)。
2. pop_trace_payload —— 按问句弹出单次判定载荷,供 graph L0 层附加 trace;
   侧信道形态,冻结接口 09-D5(MetricQueryEngine.resolve)零改。
3. flush_pending —— scheduler 周期任务(600s):小时窗聚合计数 upsert 落库
   analytics_head_telemetry_agg(运行时 CREATE TABLE IF NOT EXISTS,对齐
   trace.py 先例,无 alembic 迁移)。

纪律:flush 失败 print 吞掉、窗口计数丢弃不回灌(与 badcase/digest 同裁决
—— 聚合观测面丢单窗可接受,不阻断主流程);单实例假设(ADR-0007)。
已知残留:fallback_intent 内按改写问句重跑 resolve 记录的事件不会被 pop,
由 _PENDING_LIMIT 有界淘汰兜底。
"""

from __future__ import annotations

import datetime as _dt
import threading

from sqlalchemy import text

from ..db import get_session

# 事件闭集:shadow 一致/分歧、on 接管、低置信放行 L3、打分失败
EVENTS = ("shadow_agree", "shadow_divergence", "head_takeover", "head_low_conf_pass", "head_error")

_PENDING_LIMIT = 1024  # trace 载荷挂单上限(未被 pop 的残留有界淘汰,最旧先出)

_DDL = """
CREATE TABLE IF NOT EXISTS analytics_head_telemetry_agg (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  window_start TIMESTAMP NOT NULL,
  mode TEXT NOT NULL,
  shadow_agree INTEGER NOT NULL DEFAULT 0,
  shadow_divergence INTEGER NOT NULL DEFAULT 0,
  head_takeover INTEGER NOT NULL DEFAULT 0,
  head_low_conf_pass INTEGER NOT NULL DEFAULT 0,
  head_error INTEGER NOT NULL DEFAULT 0,
  updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
  UNIQUE (window_start, mode)
);
CREATE INDEX IF NOT EXISTS ix_head_telemetry_agg_window ON analytics_head_telemetry_agg(window_start);
"""

_ready = False
_lock = threading.Lock()
# (小时窗, mode) → {事件: 计数};窗口键 = 向下取整到小时的 UTC naive
_counters: dict[tuple[_dt.datetime, str], dict[str, int]] = {}
# question[:200] → 单次判定载荷(graph 的 L0/head 层附加用,pop 一次性)
_pending: dict[str, dict] = {}


def hour_window(ts: _dt.datetime | None = None) -> _dt.datetime:
    """窗口键:aware 归一 UTC 后向下取整到小时(与 digest.py 库钟同源纪律)。"""
    if ts is None:
        ts = _dt.datetime.now(_dt.UTC)
    elif ts.tzinfo is not None:
        ts = ts.astimezone(_dt.UTC)
    return ts.replace(tzinfo=None, minute=0, second=0, microsecond=0)


def record_event(
    event: str,
    *,
    question: str,
    mode: str,
    head_label: str | None = None,
    head_conf: float | None = None,
    l0_metric: str | None = None,
) -> None:
    """记一笔判定事件(同步零 IO,永不抛 —— 观测面不炸 L0)。"""
    try:
        payload = {
            "event": event,
            "mode": mode,
            "l0_metric": l0_metric,
            "head_label": head_label,
            "head_conf": round(head_conf, 2) if head_conf is not None else None,
        }
        with _lock:
            bucket = _counters.setdefault((hour_window(), mode), dict.fromkeys(EVENTS, 0))
            bucket[event] = bucket.get(event, 0) + 1
            key = (question or "")[:200]
            _pending.pop(key, None)  # 重问刷新位置(FIFO 淘汰口径:最旧先出)
            _pending[key] = payload
            while len(_pending) > _PENDING_LIMIT:
                oldest = next(iter(_pending))
                _pending.pop(oldest)
    except Exception as err:  # pragma: no cover - 观测面自兜底,正常路径不可达
        print(f"[HeadTelemetry] 记录失败(观测面不反噬主流程): {err}")


def pop_trace_payload(question: str) -> dict | None:
    """弹出该问句的单次判定载荷(一次性;无记录返回 None)。"""
    with _lock:
        return _pending.pop((question or "")[:200], None)


def snapshot_and_reset_counters() -> dict[tuple[_dt.datetime, str], dict[str, int]]:
    """整体取走窗口计数(取走即清,flush 侧独占)。"""
    global _counters
    with _lock:
        snap = _counters
        _counters = {}
        return snap


def to_rows(snapshot: dict[tuple[_dt.datetime, str], dict[str, int]]) -> list[dict]:
    """窗口计数 → 落库绑定参数行(纯函数)。"""
    rows = []
    for (window, mode), counts in snapshot.items():
        row = {"window_start": window, "mode": mode}
        for event in EVENTS:
            row[event] = int(counts.get(event, 0))
        rows.append(row)
    return rows


async def _ensure_table() -> None:
    global _ready
    if _ready:
        return
    # commit 必须在 async-with 内:get_session 退出即 close,未提交的 DDL 事务
    # 会被回滚(get_session 契约「未提交即回滚」;2026-10-16 实弹探针坐实)
    async with get_session() as session:
        for stmt in _DDL.split(";"):
            if stmt.strip():
                await session.execute(text(stmt))
        await session.commit()
    _ready = True


async def _write_rows(rows: list[dict]) -> None:
    """DB IO 缝(测试 monkeypatch 点):逐行增量 upsert。"""
    await _ensure_table()
    async with get_session() as session:
        for row in rows:
            assigns = ", ".join(f"{e} = analytics_head_telemetry_agg.{e} + EXCLUDED.{e}" for e in EVENTS)
            cols = ", ".join(row)
            binds = ", ".join(f":{k}" for k in row)
            await session.execute(
                text(
                    f"INSERT INTO analytics_head_telemetry_agg ({cols}) VALUES ({binds}) "
                    f"ON CONFLICT (window_start, mode) DO UPDATE SET {assigns}, updated_at = NOW()"
                ),
                row,
            )
        await session.commit()


async def flush_pending() -> dict:
    """scheduler 周期任务:窗口计数聚合计数落库(整体 try/except,不抛)。"""
    try:
        snapshot = snapshot_and_reset_counters()
        events = sum(sum(c.values()) for c in snapshot.values())
        if not snapshot:
            return {"windows": 0, "events": 0}
        await _write_rows(to_rows(snapshot))
        windows = len(snapshot)
        print(f"[HeadTelemetry] 聚合落库: {windows} 窗口 {events} 事件")
        return {"windows": windows, "events": events}
    except Exception as err:
        # 丢弃不回灌:观测面丢单窗可接受,不阻断主流程(badcase/digest 同裁决)
        print(f"[HeadTelemetry] 聚合落库失败(观测面不反噬主流程): {err}")
        return {"windows": 0, "events": 0, "error": str(err)}


def reset_for_tests() -> None:
    """清空进程内模块态(测试隔离;生产不调用)。"""
    global _ready
    with _lock:
        _counters.clear()
        _pending.clear()
    _ready = False
