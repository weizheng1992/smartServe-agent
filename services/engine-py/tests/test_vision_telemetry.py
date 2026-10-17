"""视觉审计遥测单测(2026-10-16 视觉加固 09,engine_py/vision/telemetry.py)。

两层验收:
1. recorder 纯函数面:record_call 计数累积 / 越界 source 防御归 none / 永不抛;
   snapshot→to_rows 形状;flush 走 _write_rows monkeypatch 缝(不触真库)。
2. analyzer 接线面:成功/模型异常/无定责三出口各记一笔、空图零记录、
   S06 钳制命中计数 —— 复用 test_vision_analyzer 的伪模型注入缝与 1px PNG 手法。

telemetry 是进程内单例,逐测 reset_for_tests 隔离(autouse 夹具)。
"""

from __future__ import annotations

import asyncio
import datetime as _dt
import itertools

import pytest

from engine_py.vision import analyzer, telemetry
from engine_py.vision.analyzer import DamageAssessment, VisionAnalysis

_PNG_1PX = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d49444154789c626001000000ffff03000006000557bfabd40000000049454e44ae426082"
)


class _FakeStructuredRunnable:
    def __init__(self, result=None, exc: Exception | None = None):
        self.result = result
        self.exc = exc

    async def ainvoke(self, messages, config=None, **kwargs):
        if self.exc:
            raise self.exc
        return self.result


class _FakeModel:
    def __init__(self, runnable: _FakeStructuredRunnable):
        self.runnable = runnable

    def with_structured_output(self, schema, method=None, **kwargs):
        return self.runnable


@pytest.fixture(autouse=True)
def _isolate_telemetry():
    telemetry.reset_for_tests()
    yield
    telemetry.reset_for_tests()


def _totals(snapshot) -> dict:
    """跨窗口聚合计数(测试只关心总量,不关心落窗)。"""
    totals = {}
    for counts in snapshot.values():
        for key, value in counts.items():
            totals[key] = totals.get(key, 0) + value
    return totals


def _naive_hour(h: int) -> _dt.datetime:
    """窗口键形态:naive UTC 整点(落库键约定,刻意 naive —— head_telemetry 同源)。"""
    return _dt.datetime(2026, 10, 16, h, 0, tzinfo=_dt.UTC).replace(tzinfo=None)


class TestRecorder:
    def test_record_call_accumulates_per_source(self):
        telemetry.record_call(source="vision", damage_level="minor", latency_ms=120)
        telemetry.record_call(source="vision", damage_level="severe", clamped=False, order_id_extracted=True)
        telemetry.record_call(source="heuristic", damage_level="minor", degraded_reason="model_error")
        snapshot = telemetry.snapshot_and_reset_counters()
        # 跨窗聚合(按 source 累加,不用覆盖写 —— 同 source 双窗时覆盖会静默丢前窗)
        by_source: dict[str, dict] = {}
        for (window, source), counts in snapshot.items():
            bucket = by_source.setdefault(source, dict.fromkeys(telemetry.COUNTERS, 0))
            for key, value in counts.items():
                bucket[key] = bucket.get(key, 0) + value
        assert by_source["vision"]["calls"] == 2
        assert by_source["vision"]["damage_minor"] == 1
        assert by_source["vision"]["damage_severe"] == 1
        assert by_source["vision"]["latency_sum_ms"] == 120
        assert by_source["heuristic"]["calls"] == 1
        assert by_source["heuristic"]["degraded_model_error"] == 1
        # 取走即清
        assert telemetry.snapshot_and_reset_counters() == {}

    def test_unknown_source_defensively_lands_in_none_and_never_raises(self):
        telemetry.record_call(source="bogus", damage_level="extreme")  # 未知枚举不得炸、不得建新桶
        telemetry.record_call(source="vision", latency_ms=-5)  # 负延迟钳 0
        snapshot = telemetry.snapshot_and_reset_counters()
        assert {source for _, source in snapshot} == {"none", "vision"}
        none_bucket = next(c for (w, s), c in snapshot.items() if s == "none")
        assert none_bucket["calls"] == 1
        assert none_bucket["damage_severe"] == 0  # 未知名目不进评级分布
        vision_bucket = next(c for (w, s), c in snapshot.items() if s == "vision")
        assert vision_bucket["latency_sum_ms"] == 0

    def test_hour_window_floors_to_hour_utc(self):
        """窗口键向下取整到小时(取整粒度改坏曾全绿 —— 2026-10-16 审查变异钉死)。"""
        ts = _dt.datetime(2026, 10, 16, 10, 37, 22, tzinfo=_dt.UTC)
        assert telemetry.hour_window(ts) == _naive_hour(10)
        assert telemetry.hour_window().tzinfo is None  # naive UTC 落库键

    def test_to_rows_shape(self):
        telemetry.record_call(source="vision", damage_level="negligible", order_id_extracted=True, latency_ms=30)
        rows = telemetry.to_rows(telemetry.snapshot_and_reset_counters())
        assert len(rows) == 1
        row = rows[0]
        assert row["source"] == "vision"
        assert set(row) == {"window_start", "source", *telemetry.COUNTERS}
        assert row["calls"] == 1 and row["damage_negligible"] == 1
        assert row["order_id_extracted"] == 1 and row["latency_sum_ms"] == 30

    def test_to_rows_and_flush_fan_out_all_window_source_buckets(self, monkeypatch):
        """多窗口×多来源必须逐桶落行(to_rows 截断变异 [:1] 曾全绿 —— 同小时内
        vision 成功 + heuristic 降级是生产常态,截断即来源占比静默失真)。"""
        written: list[list[dict]] = []

        async def _fake_write_rows(rows):
            written.append(rows)

        monkeypatch.setattr(telemetry, "_write_rows", _fake_write_rows)
        windows = itertools.cycle([_naive_hour(10), _naive_hour(10), _naive_hour(11)])
        monkeypatch.setattr(telemetry, "hour_window", lambda ts=None: next(windows))
        telemetry.record_call(source="vision", damage_level="minor")
        telemetry.record_call(source="heuristic", degraded_reason="model_error")
        telemetry.record_call(source="vision", damage_level="severe")

        rows = telemetry.to_rows(telemetry.snapshot_and_reset_counters())
        assert len(rows) == 3
        by_key = {(r["window_start"], r["source"]): r for r in rows}
        assert by_key[(_naive_hour(10), "vision")]["damage_minor"] == 1
        assert by_key[(_naive_hour(10), "heuristic")]["degraded_model_error"] == 1
        assert by_key[(_naive_hour(11), "vision")]["damage_severe"] == 1

        # flush 同形:逐桶一行,summary 计全量调用数
        telemetry.record_call(source="vision", damage_level="minor")
        telemetry.record_call(source="heuristic", degraded_reason="model_error")
        telemetry.record_call(source="vision", damage_level="severe")
        summary = asyncio.run(telemetry.flush_pending())
        assert summary == {"windows": 3, "calls": 3}
        assert len(written[0]) == 3

    def test_flush_writes_rows_and_resets(self, monkeypatch):
        written: list[list[dict]] = []

        async def _fake_write_rows(rows):
            written.append(rows)

        monkeypatch.setattr(telemetry, "_write_rows", _fake_write_rows)
        telemetry.record_call(source="heuristic", degraded_reason="unreadable")
        summary = asyncio.run(telemetry.flush_pending())
        assert summary == {"windows": 1, "calls": 1}
        assert len(written) == 1 and written[0][0]["source"] == "heuristic"
        # 空窗口不触库
        assert asyncio.run(telemetry.flush_pending()) == {"windows": 0, "calls": 0}
        assert len(written) == 1

    def test_flush_failure_swallows_and_drops_window(self, monkeypatch):
        async def _boom(rows):
            raise RuntimeError("db down")

        monkeypatch.setattr(telemetry, "_write_rows", _boom)
        telemetry.record_call(source="vision", damage_level="minor")
        summary = asyncio.run(telemetry.flush_pending())
        assert summary["windows"] == 0 and "error" in summary
        # 丢单窗不回灌:计数已被取走
        assert telemetry.snapshot_and_reset_counters() == {}


class TestAnalyzerWiring:
    def test_success_path_records_vision_source(self):
        parsed = VisionAnalysis(
            visual_summary="一双鞋",
            damage_assessment=DamageAssessment(
                damage_level="minor", summary="小划痕", confidence=0.9, suggested_action="human_review"
            ),
        )
        res = asyncio.run(
            analyzer.analyze_images(
                ["https://cdn.store.com/x.jpg"], "有点划痕 ORD-77889", model=_FakeModel(_FakeStructuredRunnable(parsed))
            )
        )
        assert res["damageAssessment"]["evidenceChannel"] == "vision"
        totals = _totals(telemetry.snapshot_and_reset_counters())
        assert totals["calls"] == 1
        assert totals["damage_minor"] == 1
        assert totals["clamp_action_hit"] == 0
        assert totals["order_id_extracted"] == 1  # 文本正则提取的 ORD-77889
        assert totals["latency_sum_ms"] >= 0

    def test_clamp_hit_counted(self):
        poisoned = VisionAnalysis(
            damage_assessment=DamageAssessment(
                damage_level="minor", summary="小划痕", confidence=0.9, suggested_action="auto_refund"
            ),
        )
        res = asyncio.run(
            analyzer.analyze_images(["https://cdn.store.com/x.jpg"], "想退", model=_FakeModel(_FakeStructuredRunnable(poisoned)))
        )
        assert res["damageAssessment"]["suggestedAction"] == "human_review"  # S06 钳制仍在
        totals = _totals(telemetry.snapshot_and_reset_counters())
        assert totals["clamp_action_hit"] == 1

    def test_model_error_with_damage_words_records_heuristic(self):
        res = asyncio.run(
            analyzer.analyze_images(
                ["https://cdn.store.com/x.jpg"],
                "鞋底开胶断裂了",
                model=_FakeModel(_FakeStructuredRunnable(exc=RuntimeError("llm down"))),
            )
        )
        assert res["damageAssessment"]["evidenceChannel"] == "heuristic"
        totals = _totals(telemetry.snapshot_and_reset_counters())
        assert totals["calls"] == 1
        assert totals["damage_minor"] == 1
        assert totals["degraded_model_error"] == 1

    def test_model_error_without_damage_words_records_none(self):
        res = asyncio.run(
            analyzer.analyze_images(
                ["https://cdn.store.com/x.jpg"],
                "帮我看看这个商品",
                model=_FakeModel(_FakeStructuredRunnable(exc=RuntimeError("llm down"))),
            )
        )
        assert res["damageAssessment"] is None
        totals = _totals(telemetry.snapshot_and_reset_counters())
        assert totals["calls"] == 1
        assert totals["degraded_model_error"] == 1
        assert totals["damage_minor"] == 0

    def test_model_success_null_damage_not_counted_as_degraded(self):
        """模型成功但拒判定责(VLM 对无破损图的常态返回)不得误入任何 degraded 计数
        (2026-10-16 审查变异:degraded 串写错曾全绿)。"""
        parsed = VisionAnalysis(visual_summary="一双完好的鞋", damage_assessment=None)
        res = asyncio.run(
            analyzer.analyze_images(
                ["https://cdn.store.com/x.jpg"],
                "帮我看看这个商品",
                model=_FakeModel(_FakeStructuredRunnable(parsed)),
            )
        )
        assert res["damageAssessment"] is None
        totals = _totals(telemetry.snapshot_and_reset_counters())
        assert totals["calls"] == 1
        assert totals["degraded_unreadable"] == 0
        assert totals["degraded_model_error"] == 0

    def test_model_success_null_damage_with_damage_words_lands_heuristic_clean(self):
        """模型拒判 × 文本含破损词 → heuristic 桶,且 degraded 双零
        (「模型拒判走词面兜底」与「模型挂了」在遥测上可区分)。"""
        parsed = VisionAnalysis(visual_summary="一只杯子", damage_assessment=None)
        res = asyncio.run(
            analyzer.analyze_images(
                ["https://cdn.store.com/x.jpg"],
                "杯子有裂开",
                model=_FakeModel(_FakeStructuredRunnable(parsed)),
            )
        )
        assert res["damageAssessment"]["evidenceChannel"] == "heuristic"
        totals = _totals(telemetry.snapshot_and_reset_counters())
        assert totals["damage_minor"] == 1
        assert totals["degraded_model_error"] == 0
        assert totals["degraded_unreadable"] == 0

    def test_unreadable_images_record_unreadable(self, tmp_path, monkeypatch):
        monkeypatch.setenv("UPLOADS_DIR", str(tmp_path))
        res = asyncio.run(
            analyzer.analyze_images(
                ["/api/uploads/missing.png"], "破损了", model=_FakeModel(_FakeStructuredRunnable(exc=AssertionError("不应调模型")))
            )
        )
        assert res["damageAssessment"]["evidenceChannel"] == "heuristic"
        totals = _totals(telemetry.snapshot_and_reset_counters())
        assert totals["degraded_unreadable"] == 1
        assert totals["degraded_model_error"] == 0

    def test_no_images_records_nothing(self):
        asyncio.run(analyzer.analyze_images([], "没图", model=_FakeModel(_FakeStructuredRunnable())))
        assert telemetry.snapshot_and_reset_counters() == {}
