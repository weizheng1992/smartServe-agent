"""视觉调用审计遥测(2026-10-16 视觉加固 09,补「vision 零遥测」缺口)。

背景:get_vision_model 刻意不入 _ResilientChatOpenAI 韧性层(视觉失败域独立
自带启发式兜底),副作用是 vision 调用在 llm_call_logs 零痕迹 —— 调了多少次、
评级来自模型还是启发式、评级分布、S06 钳制命中几次、耗时几何,全库不可查;
后续自动闸(④ confidence 阈值 / ② 指纹命中阈值 / ⑧ velocity 阈值)都没有
标定依据。本模块镜像 analytics/head_telemetry.py 三段式:

1. record_call —— analyzer 出口统一记账(成功/图全不可读/模型异常三出口各一笔,
   空图入口不记):进程内线程安全,同步零 IO、永不抛(观测面不炸视觉主链路)。
   source 闭集 {vision, heuristic, none}。
2. flush_pending —— scheduler 周期任务(600s):小时窗聚合 upsert 落库
   vision_audit_agg(运行时 CREATE TABLE IF NOT EXISTS,对齐 trace.py /
   head_telemetry.py 先例,无 alembic 迁移)。
3. reset_for_tests —— 测试隔离(生产不调用)。

纪律:只记聚合计数,图内容零落库(spec 视觉加固纪律 5);flush 失败 print
吞掉、窗口计数丢弃不回灌(head_telemetry 同裁决);单实例假设(ADR-0007)。
"""

from __future__ import annotations

import datetime as _dt
import threading

from sqlalchemy import text

from ..db import get_session

# 来源闭集:vision(模型评级)/ heuristic(启发式评级,含降级)/ none(全链无定责)
SOURCES = ("vision", "heuristic", "none")

# 计数列闭集(DDL / to_rows / upsert 三处同源,加列三处同步)
COUNTERS = (
    "calls",
    "damage_negligible",
    "damage_minor",
    "damage_severe",
    "clamp_action_hit",
    "severe_conf_clamp",
    "order_id_extracted",
    "degraded_model_error",
    "degraded_unreadable",
    "latency_sum_ms",
    "fraud_reuse_hit",
    "product_verify_downgrade",
    "claim_velocity_hit",
    "injection_flag_hit",
)

_DDL = """
CREATE TABLE IF NOT EXISTS vision_audit_agg (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  window_start TIMESTAMP NOT NULL,
  source TEXT NOT NULL,
  calls INTEGER NOT NULL DEFAULT 0,
  damage_negligible INTEGER NOT NULL DEFAULT 0,
  damage_minor INTEGER NOT NULL DEFAULT 0,
  damage_severe INTEGER NOT NULL DEFAULT 0,
  clamp_action_hit INTEGER NOT NULL DEFAULT 0,
  severe_conf_clamp INTEGER NOT NULL DEFAULT 0,
  order_id_extracted INTEGER NOT NULL DEFAULT 0,
  degraded_model_error INTEGER NOT NULL DEFAULT 0,
  degraded_unreadable INTEGER NOT NULL DEFAULT 0,
  latency_sum_ms BIGINT NOT NULL DEFAULT 0,
  fraud_reuse_hit INTEGER NOT NULL DEFAULT 0,
  product_verify_downgrade INTEGER NOT NULL DEFAULT 0,
  claim_velocity_hit INTEGER NOT NULL DEFAULT 0,
  injection_flag_hit INTEGER NOT NULL DEFAULT 0,
  updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
  UNIQUE (window_start, source)
);
CREATE INDEX IF NOT EXISTS ix_vision_audit_agg_window ON vision_audit_agg(window_start);
ALTER TABLE vision_audit_agg ADD COLUMN IF NOT EXISTS fraud_reuse_hit INTEGER NOT NULL DEFAULT 0;
ALTER TABLE vision_audit_agg ADD COLUMN IF NOT EXISTS severe_conf_clamp INTEGER NOT NULL DEFAULT 0;
ALTER TABLE vision_audit_agg ADD COLUMN IF NOT EXISTS product_verify_downgrade INTEGER NOT NULL DEFAULT 0;
ALTER TABLE vision_audit_agg ADD COLUMN IF NOT EXISTS claim_velocity_hit INTEGER NOT NULL DEFAULT 0;
ALTER TABLE vision_audit_agg ADD COLUMN IF NOT EXISTS injection_flag_hit INTEGER NOT NULL DEFAULT 0;
"""

_ready = False
_lock = threading.Lock()
# (小时窗, source) → {计数列: 累计};窗口键 = 向下取整到小时的 UTC naive
_counters: dict[tuple[_dt.datetime, str], dict[str, int]] = {}


def hour_window(ts: _dt.datetime | None = None) -> _dt.datetime:
    """窗口键:aware 归一 UTC 后向下取整到小时(head_telemetry 同源纪律)。"""
    if ts is None:
        ts = _dt.datetime.now(_dt.UTC)
    elif ts.tzinfo is not None:
        ts = ts.astimezone(_dt.UTC)
    return ts.replace(tzinfo=None, minute=0, second=0, microsecond=0)


def record_call(
    *,
    source: str,
    damage_level: str | None = None,
    clamped: bool = False,
    low_conf_severe: bool = False,
    order_id_extracted: bool = False,
    degraded_reason: str | None = None,
    latency_ms: int | None = None,
) -> None:
    """记一笔视觉调用(同步零 IO,永不抛 —— 观测面不炸视觉主链路)。

    source 越界值防御性归 none(调用方闭集由 analyzer 构造保证,此为兜底)。
    """
    try:
        if source not in SOURCES:
            source = "none"
        with _lock:
            bucket = _counters.setdefault((hour_window(), source), dict.fromkeys(COUNTERS, 0))
            bucket["calls"] += 1
            if damage_level == "negligible":
                bucket["damage_negligible"] += 1
            elif damage_level == "minor":
                bucket["damage_minor"] += 1
            elif damage_level == "severe":
                bucket["damage_severe"] += 1
            if clamped:
                bucket["clamp_action_hit"] += 1
            if low_conf_severe:
                bucket["severe_conf_clamp"] += 1
            if order_id_extracted:
                bucket["order_id_extracted"] += 1
            if degraded_reason == "model_error":
                bucket["degraded_model_error"] += 1
            elif degraded_reason == "unreadable":
                bucket["degraded_unreadable"] += 1
            if latency_ms is not None:
                bucket["latency_sum_ms"] += max(0, int(latency_ms))
    except Exception as err:  # pragma: no cover - 观测面自兜底,正常路径不可达
        print(f"[VisionTelemetry] 记录失败(观测面不反噬主流程): {err}")


def record_reuse_hit(*, hits: int = 1) -> None:
    """记图证跨用户复用命中(2026-10-17 视觉加固 ②,vision_parse 侧单独累计)。

    与 record_call 分离:命中发生在评级记账之后,严禁再 +1 calls(否则调用量
    虚高)。桶固定挂 vision 来源、calls 保持 0 的空桶是合法形态。
    """
    try:
        with _lock:
            bucket = _counters.setdefault((hour_window(), "vision"), dict.fromkeys(COUNTERS, 0))
            bucket["fraud_reuse_hit"] += max(1, int(hits))
    except Exception as err:  # pragma: no cover - 观测面自兜底,正常路径不可达
        print(f"[VisionTelemetry] 复用命中记录失败(观测面不反噬主流程): {err}")


def record_verify_downgrade() -> None:
    """记图商品真伪校验不过的降级(2026-10-17 视觉加固 ③,disambiguator 侧)。

    matched 自动注入被校验拦下 → 降 ambiguous 出选择卡;与 record_call 分离
    (不虚增 calls),桶固定挂 vision 来源。
    """
    try:
        with _lock:
            bucket = _counters.setdefault((hour_window(), "vision"), dict.fromkeys(COUNTERS, 0))
            bucket["product_verify_downgrade"] += 1
    except Exception as err:  # pragma: no cover - 观测面自兜底,正常路径不可达
        print(f"[VisionTelemetry] 真伪校验降级记录失败(观测面不反噬主流程): {err}")


def record_velocity_hit() -> None:
    """记索赔 velocity 闸命中(2026-10-17 视觉加固 ⑧,executor 4.4 侧单独累计)。

    同用户滚动窗口带图索赔覆盖多单 → 免签关闭走 HITL;与 record_call 分离
    (不虚增 calls),桶固定挂 vision 来源。
    """
    try:
        with _lock:
            bucket = _counters.setdefault((hour_window(), "vision"), dict.fromkeys(COUNTERS, 0))
            bucket["claim_velocity_hit"] += 1
    except Exception as err:  # pragma: no cover - 观测面自兜底,正常路径不可达
        print(f"[VisionTelemetry] velocity 命中记录失败(观测面不反噬主流程): {err}")


def record_injection_flag() -> None:
    """记图内指令注入特征命中(2026-10-17 视觉加固 ⑦ v1,analyzer 出口)。

    ocr_text 命中系统导向祈使词表 → injectionFlag + auto_refund 压制;与
    record_call 分离(不虚增 calls),桶固定挂 vision 来源。
    """
    try:
        with _lock:
            bucket = _counters.setdefault((hour_window(), "vision"), dict.fromkeys(COUNTERS, 0))
            bucket["injection_flag_hit"] += 1
    except Exception as err:  # pragma: no cover - 观测面自兜底,正常路径不可达
        print(f"[VisionTelemetry] 注入特征记录失败(观测面不反噬主流程): {err}")


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
    for (window, source), counts in snapshot.items():
        row = {"window_start": window, "source": source}
        for counter in COUNTERS:
            row[counter] = int(counts.get(counter, 0))
        rows.append(row)
    return rows


async def _ensure_table() -> None:
    global _ready
    if _ready:
        return
    # commit 必须在 async-with 内:get_session 退出即 close,未提交的 DDL 事务
    # 会被回滚(get_session 契约「未提交即回滚」;head_telemetry 同注释先例)
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
            assigns = ", ".join(f"{c} = vision_audit_agg.{c} + EXCLUDED.{c}" for c in COUNTERS)
            cols = ", ".join(row)
            binds = ", ".join(f":{k}" for k in row)
            await session.execute(
                text(
                    f"INSERT INTO vision_audit_agg ({cols}) VALUES ({binds}) "
                    f"ON CONFLICT (window_start, source) DO UPDATE SET {assigns}, updated_at = NOW()"
                ),
                row,
            )
        await session.commit()


async def flush_pending() -> dict:
    """scheduler 周期任务:窗口聚合落库(整体 try/except,不抛)。"""
    try:
        snapshot = snapshot_and_reset_counters()
        calls = sum(int(c.get("calls", 0)) for c in snapshot.values())
        if not snapshot:
            return {"windows": 0, "calls": 0}
        await _write_rows(to_rows(snapshot))
        windows = len(snapshot)
        print(f"[VisionTelemetry] 聚合落库: {windows} 窗口 {calls} 次调用")
        return {"windows": windows, "calls": calls}
    except Exception as err:
        # 丢弃不回灌:观测面丢单窗可接受,不阻断主流程(head_telemetry 同裁决)
        print(f"[VisionTelemetry] 聚合落库失败(观测面不反噬主流程): {err}")
        return {"windows": 0, "calls": 0, "error": str(err)}


def reset_for_tests() -> None:
    """清空进程内模块态(测试隔离;生产不调用)。"""
    global _ready
    with _lock:
        _counters.clear()
    _ready = False
