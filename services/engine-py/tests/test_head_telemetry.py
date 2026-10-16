"""分类头服务期遥测单测(head_telemetry recorder + 聚合纯函数;免 DB 免网络)。

DB IO 缝(_write_rows)一律 monkeypatch 假体:落库 SQL 的真实执行不在本文件
钉 —— 建表/写入走运行时 DDL,由全量套件在真库子集覆盖;此处钉的是
窗口切分/分桶计数/pop 一次性/有界淘汰/flush 容错等观测面语义。
"""

from __future__ import annotations

import asyncio
import datetime as _dt
import threading

import pytest

from engine_py.analytics import head_telemetry as ht


@pytest.fixture(autouse=True)
def _reset_telemetry():
    ht.reset_for_tests()
    yield
    ht.reset_for_tests()


def _naive(*args: int) -> _dt.datetime:
    """库钟同源的 UTC naive 构造(digest.py 纪律:aware 生成后剥 tzinfo)。"""
    return _dt.datetime(*args, tzinfo=_dt.UTC).replace(tzinfo=None)


def test_hour_window_floor():
    naive = _naive(2026, 10, 16, 9, 59, 59)
    assert ht.hour_window(naive) == _naive(2026, 10, 16, 9, 0, 0)
    assert ht.hour_window(_naive(2026, 10, 16, 10, 0, 0)) == _naive(2026, 10, 16, 10, 0, 0)
    # aware 输入归一 UTC 再取整(东八区 18:30 → UTC 10:00)
    aware = _dt.datetime(2026, 10, 16, 18, 30, 0, tzinfo=_dt.timezone(_dt.timedelta(hours=8)))
    assert ht.hour_window(aware) == _naive(2026, 10, 16, 10, 0, 0)


def test_record_event_buckets_by_window_and_mode():
    ht.record_event("shadow_divergence", question="q1", mode="shadow", head_label="gmv", head_conf=0.71, l0_metric="volume")
    ht.record_event("shadow_agree", question="q2", mode="shadow", head_label="gmv", head_conf=0.8, l0_metric="gmv")
    ht.record_event("shadow_agree", question="q3", mode="on", head_label="gmv", head_conf=0.8, l0_metric="gmv")
    snap = ht.snapshot_and_reset_counters()
    assert len(snap) == 2  # 同窗不同 mode 分桶
    for (window, mode), counts in snap.items():
        assert set(counts) == set(ht.EVENTS)  # 五事件键恒齐(缺省 0)
        assert window.minute == 0 and window.second == 0
    shadow = next(c for (w, m), c in snap.items() if m == "shadow")
    on = next(c for (w, m), c in snap.items() if m == "on")
    assert shadow["shadow_divergence"] == 1 and shadow["shadow_agree"] == 1
    assert on["shadow_agree"] == 1
    assert ht.snapshot_and_reset_counters() == {}  # 取走即清


def test_pop_trace_payload_once():
    ht.record_event("head_takeover", question="销量榜", mode="on", head_label="volume", head_conf=0.9)
    payload = ht.pop_trace_payload("销量榜")
    assert payload == {"event": "head_takeover", "mode": "on", "l0_metric": None, "head_label": "volume", "head_conf": 0.9}
    assert ht.pop_trace_payload("销量榜") is None  # 一次性,无残留


def test_pending_bounded():
    for i in range(ht._PENDING_LIMIT + 50):
        ht.record_event("shadow_agree", question=f"问题 {i}", mode="shadow", head_label="gmv", head_conf=0.5)
    assert len(ht._pending) == ht._PENDING_LIMIT
    assert ht.pop_trace_payload("问题 0") is None  # 最旧被有界淘汰
    assert ht.pop_trace_payload(f"问题 {ht._PENDING_LIMIT + 49}") is not None  # 最新仍在


def test_to_rows_shape():
    ht.record_event("head_error", question="x", mode="shadow")
    rows = ht.to_rows(ht.snapshot_and_reset_counters())
    assert len(rows) == 1
    row = rows[0]
    assert set(row) == {"window_start", "mode", *ht.EVENTS}
    assert row["mode"] == "shadow" and row["head_error"] == 1 and row["shadow_agree"] == 0


def test_flush_empty_skips_db(monkeypatch):
    def _must_not_write(rows):
        raise AssertionError("空计数不应触库")

    monkeypatch.setattr(ht, "_write_rows", _must_not_write)
    assert asyncio.run(ht.flush_pending()) == {"windows": 0, "events": 0}


def test_flush_writes_rows_and_returns_summary(monkeypatch):
    captured: dict = {}

    async def fake_write(rows):
        captured["rows"] = rows

    monkeypatch.setattr(ht, "_write_rows", fake_write)
    ht.record_event("shadow_divergence", question="a", mode="shadow", head_label="gmv", head_conf=0.9, l0_metric="gmv")
    ht.record_event("head_takeover", question="b", mode="on", head_label="gmv", head_conf=0.9)
    assert asyncio.run(ht.flush_pending()) == {"windows": 2, "events": 2}
    assert len(captured["rows"]) == 2
    assert asyncio.run(ht.flush_pending()) == {"windows": 0, "events": 0}  # flush 后清空


def test_flush_failure_swallows_and_reports(monkeypatch):
    async def _boom(rows):
        raise RuntimeError("db down")

    monkeypatch.setattr(ht, "_write_rows", _boom)
    ht.record_event("shadow_agree", question="a", mode="shadow", head_label="gmv", head_conf=0.5)
    summary = asyncio.run(ht.flush_pending())  # 不抛:观测面不反噬主流程
    assert summary["windows"] == 0 and "error" in summary


def test_concurrent_record_smoke():
    """线程并发计数不丢(recorder 被 asyncio.to_thread 并发调用是常态)。"""
    n_threads, per_thread = 8, 50
    barrier = threading.Barrier(n_threads)

    def worker():
        barrier.wait()
        for i in range(per_thread):
            ht.record_event("shadow_agree", question=f"q-{threading.get_ident()}-{i}", mode="shadow", head_label="gmv", head_conf=0.5)

    threads = [threading.Thread(target=worker) for _ in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    snap = ht.snapshot_and_reset_counters()
    assert sum(c["shadow_agree"] for c in snap.values()) == n_threads * per_thread
