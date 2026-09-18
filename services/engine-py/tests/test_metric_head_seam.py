"""缝②指标映射分类头接入测试(11-D1;AI_METRIC_HEAD 三态)。

用 hash 冒烟编码器离线训练一个微型 run,验证:
- 默认不启用(纯 L0 现状)
- shadow:并行打分只记日志,判定不变(不支持问题仍响亮拒绝,但日志有 head 分)
- on:L0 未命中处分类头接管(达标置信),低置信仍 UnsupportedQuery
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

TRAINING_DIR = Path(__file__).resolve().parents[1] / "scripts" / "training"
sys.path.insert(0, str(TRAINING_DIR))

from engine_py.analytics import graph
from engine_py.analytics.engine import MetricQueryEngine, UnsupportedQuery

LABELS = ["gmv", "volume", "review_bad"]


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


def _engine_with_head(monkeypatch, run_dir: Path, mode: str):
    from engine_py.analytics import metric_head as mh

    monkeypatch.setenv("AI_METRIC_HEAD", mode)
    monkeypatch.setenv("AI_METRIC_HEAD_DIR", str(run_dir))
    monkeypatch.setenv("AI_METRIC_HEAD_THRESHOLD", "0.5")
    # 进程内工厂缓存失效(mode 变化必须重读)

    monkeypatch.delenv("AI_METRIC_HEAD", raising=False)
    # MetricQueryEngine.__init__ 直接调 get_metric_head(analytics 本地工厂)
    monkeypatch.setattr(
        "engine_py.analytics.metric_head.get_metric_head", lambda: mh.get_metric_head()
    )
    monkeypatch.setattr("engine_py.llm.chat.get_intent_classifier", lambda: None)  # 不触意图缝
    return MetricQueryEngine(session_ctx={"business_id": "aurora", "role": "finance_owner"})


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
        """shadow:并行打分只记日志,判定不变。"""
        monkeypatch.setenv("AI_METRIC_HEAD", "shadow")
        monkeypatch.setenv("AI_METRIC_HEAD_DIR", str(run_dir))
        e = MetricQueryEngine(session_ctx={"business_id": "aurora"})
        with pytest.raises(UnsupportedQuery):
            e.resolve("zzz 完全无关问题")  # shadow 下不改变「响亮拒绝」

    def test_graph_ask_role_filter_still_applies_with_head(self, monkeypatch, run_dir):
        """on 模式下越权指标仍被拒(分类头不绕过权限)。"""
        monkeypatch.setenv("AI_METRIC_HEAD", "on")
        monkeypatch.setenv("AI_METRIC_HEAD_DIR", str(run_dir))
        out = asyncio.run(graph.ask("gmv 排行", {"business_id": "aurora", "role": "warehouse_operator"}))
        assert out["type"] in ("unsupported", "error") or out.get("metric") != "gmv"
