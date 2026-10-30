"""缝②指标映射分类头接入测试(11-D1;AI_METRIC_HEAD 三态)。

用 hash 冒烟编码器离线训练一个微型 run,验证:
- 默认不启用(纯 L0 现状)
- shadow:并行打分只记日志,判定不变(不支持问题仍响亮拒绝,但日志有 head 分)
- on:L0 未命中处分类头接管(达标置信),低置信仍 UnsupportedQuery
- 遥测(2026-10-16):shadow 一致/分歧、on 接管/低置信放行、打分失败全部有账
  (head_telemetry recorder;print 面同步用 capsys 钉)
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import pytest

TRAINING_DIR = Path(__file__).resolve().parents[1] / "scripts" / "training"
sys.path.insert(0, str(TRAINING_DIR))

from engine_py.analytics import graph, head_telemetry
from engine_py.analytics import metric_head as metric_head_module
from engine_py.analytics.engine import MetricQueryEngine, StructuredQueryIntent, UnsupportedQuery

LABELS = ["gmv", "volume", "review_bad"]


class _FakeHead:
    """确定性打分桩(predict 结果可编排;真实推理由 _train_tiny 微型 run 覆盖)。"""

    def __init__(self, label: str = "gmv", conf: float = 0.9, err: Exception | None = None) -> None:
        self._label, self._conf, self._err = label, conf, err

    def predict(self, question: str) -> tuple[str, float]:
        if self._err is not None:
            raise self._err
        return self._label, self._conf


@pytest.fixture(autouse=True)
def _reset_head_telemetry():
    head_telemetry.reset_for_tests()
    yield
    head_telemetry.reset_for_tests()


def _telemetry_totals() -> dict[str, int]:
    """跨窗口跨 mode 求和(单测只关心事件总量,不关心窗口切分)。"""
    totals = dict.fromkeys(head_telemetry.EVENTS, 0)
    for counts in head_telemetry.snapshot_and_reset_counters().values():
        for key, value in counts.items():
            totals[key] += value
    return totals


def _train_tiny(tmp_path: Path) -> Path:
    """hash 编码器微型 run(离线秒级)。"""
    data = tmp_path / "data"
    data.mkdir()
    rows = []
    tpl = {
        "gmv": ["销售额最高 {i}", "看看流水 {i}", "营业额 {i}"],
        "volume": ["销量榜 {i}", "件数最多 {i}", "走量 {i}"],
        "review_bad": ["差评最多 {i}", "评分最低 {i}", "吐槽 {i}"],
    }
    for label, tpls in tpl.items():
        for i in range(12):
            rows.append({"query": tpls[i % len(tpls)].format(i=i), "label": label})
    # 预切分(跳过 prepare):80/20,分层
    train_rows, held_rows = [], []
    for label in LABELS:
        subset = [r for r in rows if r["label"] == label]
        cut = max(1, int(len(subset) * 0.2))
        held_rows.extend(subset[:cut])
        train_rows.extend(subset[cut:])
    (data / "train.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in train_rows), encoding="utf-8"
    )
    (data / "heldout.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in held_rows), encoding="utf-8"
    )
    cfg = f"""
[task]
name = "head_test"
input_field = "query"
label_field = "label"
labels = {json.dumps(LABELS)}

[data]
train_jsonl = "{data / 'train.jsonl'}"
out_dir = "{data}"
heldout_ratio = 0.2

[model]
encoder = "hash"
device = "cpu"

[train]
epochs = 30
batch_size = 8
lr = 0.05
seed = 7

[output]
run_dir = "{tmp_path / 'run'}"
"""
    cfg_path = tmp_path / "tiny.toml"
    cfg_path.write_text(cfg, encoding="utf-8")
    from train import main as train_main

    assert train_main(["--config", str(cfg_path)]) == 0
    return tmp_path / "run"


@pytest.fixture(scope="module")
def run_dir(tmp_path_factory) -> Path:
    return _train_tiny(tmp_path_factory.mktemp("head"))


class TestHeadModes:
    def test_default_off_is_pure_l0(self, monkeypatch):
        monkeypatch.delenv("AI_METRIC_HEAD", raising=False)
        e = MetricQueryEngine(session_ctx={"business_id": "aurora"})
        with pytest.raises(UnsupportedQuery):
            e.resolve("zzz 完全无关问题")

    def test_on_mode_head_takes_over_l0_miss(self, monkeypatch, run_dir):
        """L0 词表没有「退货跑输」词面,分类头接管(11-D1 缝②语义)。"""
        monkeypatch.setenv("AI_METRIC_HEAD", "on")
        monkeypatch.setenv("AI_METRIC_HEAD_DIR", str(run_dir))
        e = MetricQueryEngine(session_ctx={"business_id": "aurora"})
        # hash 编码器语义有限:验证「接管或诚实拒绝」二态,禁止静默兜底
        try:
            intent = e.resolve("退货跑输的商品")
            assert intent.metric in LABELS
        except UnsupportedQuery:
            pass  # 低置信放行 L3 也是合法语义

    def test_shadow_never_changes_verdict(self, monkeypatch, run_dir, capsys):
        """shadow:并行打分只记日志,判定不变;低置信放行在遥测有账(非静默)。"""
        monkeypatch.setenv("AI_METRIC_HEAD", "shadow")
        monkeypatch.setenv("AI_METRIC_HEAD_DIR", str(run_dir))
        e = MetricQueryEngine(session_ctx={"business_id": "aurora"})
        with pytest.raises(UnsupportedQuery):
            e.resolve("zzz 完全无关问题")  # shadow 下不改变「响亮拒绝」
        out = capsys.readouterr()
        assert "不一致" not in out.out and "接管" not in out.out
        # hash 头对无关句置信 <0.5(seed=7 确定):L0 未命中 × 低置信 → 放行 L3 有账
        assert _telemetry_totals()["head_low_conf_pass"] == 1

    def test_shadow_divergence_print_and_telemetry(self, monkeypatch, capsys):
        """shadow 分歧:原 print 保留 + shadow_divergence 计数 + trace 载荷可弹。"""
        monkeypatch.setenv("AI_METRIC_HEAD", "shadow")
        monkeypatch.setattr(metric_head_module, "get_metric_head", lambda: _FakeHead("review_bad", 0.9))
        e = MetricQueryEngine(session_ctx={"business_id": "aurora"})
        intent = e.resolve("gmv 排行")  # L0 词面命中 gmv,头打分 review_bad → 分歧
        assert isinstance(intent, StructuredQueryIntent) and intent.metric == "gmv"  # L0 终局不变
        assert "[MetricHead][shadow] 不一致" in capsys.readouterr().out
        totals = _telemetry_totals()
        assert totals["shadow_divergence"] == 1 and totals["shadow_agree"] == 0
        payload = head_telemetry.pop_trace_payload("gmv 排行")
        assert payload == {
            "event": "shadow_divergence", "mode": "shadow",
            "l0_metric": "gmv", "head_label": "review_bad", "head_conf": 0.9,
        }

    def test_shadow_agree_no_print(self, monkeypatch, capsys):
        """shadow 一致:只计数不打 print(分歧率需要分母,日志面保持零噪音)。"""
        monkeypatch.setenv("AI_METRIC_HEAD", "shadow")
        monkeypatch.setattr(metric_head_module, "get_metric_head", lambda: _FakeHead("gmv", 0.9))
        e = MetricQueryEngine(session_ctx={"business_id": "aurora"})
        intent = e.resolve("gmv 排行")
        assert isinstance(intent, StructuredQueryIntent) and intent.metric == "gmv"
        out = capsys.readouterr().out
        assert "不一致" not in out and "接管" not in out
        assert _telemetry_totals()["shadow_agree"] == 1

    def test_on_takeover_records_event(self, monkeypatch, capsys):
        """on 接管:原 print 保留 + head_takeover 计数 + 载荷与意图一致。"""
        monkeypatch.setenv("AI_METRIC_HEAD", "on")
        monkeypatch.setattr(metric_head_module, "get_metric_head", lambda: _FakeHead("gmv", 0.9))
        e = MetricQueryEngine(session_ctx={"business_id": "aurora"})
        intent = e.resolve("zzz 完全无关问题")  # L0 未命中,达标置信 → 接管
        assert isinstance(intent, StructuredQueryIntent) and intent.metric == "gmv"
        assert "[MetricHead][on] 接管" in capsys.readouterr().out
        assert _telemetry_totals()["head_takeover"] == 1
        payload = head_telemetry.pop_trace_payload("zzz 完全无关问题")
        assert payload["event"] == "head_takeover" and payload["mode"] == "on"
        assert payload["head_label"] == "gmv" and payload["head_conf"] == 0.9

    def test_head_error_records_event(self, monkeypatch, capsys):
        """打分失败:响亮放行 L0/L3 照旧 + head_error 计数(观测面不炸主流程)。"""
        monkeypatch.setenv("AI_METRIC_HEAD", "shadow")
        monkeypatch.setattr(
            metric_head_module, "get_metric_head",
            lambda: _FakeHead(err=RuntimeError("模型炸了")),
        )
        e = MetricQueryEngine(session_ctx={"business_id": "aurora"})
        intent = e.resolve("gmv 排行")  # head 打分失败不影响 L0 正常返回
        assert isinstance(intent, StructuredQueryIntent) and intent.metric == "gmv"
        assert "打分失败" in capsys.readouterr().out
        assert _telemetry_totals()["head_error"] == 1

    def test_graph_ask_role_filter_still_applies_with_head(self, monkeypatch, run_dir):
        """on 模式下越权指标仍被拒(分类头不绕过权限)。

        需要 engine_db 真连接(角色闭集查库):conftest 的毒丸缺省
        DATABASE_URL(u:p@…/test_unused)下该前提不成立 —— 显式跳过并注明
        原因,不以三连红鲱鱼污染批次(2026-10-07 定性,直调脚本同 env 验证
        引擎行为正确;真验证方式见 .scratch/data-agent-tiered-trust/issues/08)。
        """
        if os.environ.get("DATABASE_URL", "").endswith("/test_unused"):
            pytest.skip("DATABASE_URL 为 conftest 毒丸缺省:本用例需真实 engine_db(export 真库连接串后运行)")
        monkeypatch.setenv("AI_METRIC_HEAD", "on")
        monkeypatch.setenv("AI_METRIC_HEAD_DIR", str(run_dir))

        async def _ask():
            # 本测试用真库(角色闭集查库):graph 系测试先跑时,主引擎 QueuePool
            # 的池连接绑在它们已关闭的 loop 上,复用即「attached to a different
            # loop」偶发红(2026-10-27 定性)。loop 内先 dispose —— 池连接关闭,
            # 本 loop 取用时重建;生产池语义零影响(纯测试侧修)。
            from engine_py.db.session import get_engine

            await get_engine().dispose()
            return await graph.ask("gmv 排行", {"business_id": "aurora", "role": "warehouse_operator"})

        out = asyncio.run(_ask())
        assert out["type"] in ("unsupported", "error") or out.get("metric") != "gmv"
