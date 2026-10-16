"""训练脚手架端到端测试(common/prepare_data/train/evaluate 全链)。

经 sys.path 注入 scripts/training 后按模块导入;encoder 一律用 "hash" 冒烟编码器
(确定性、不下载模型),数据为合成三分类(类关键词互不重叠,hash n-gram 线性可分),
不依赖 DB / 网络 / 真实 bge——CI 可全量跑。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

TRAINING_DIR = Path(__file__).resolve().parents[1] / "scripts" / "training"
sys.path.insert(0, str(TRAINING_DIR))

import plot_curve
import train
from common import classification_report, write_json_atomic
from evaluate import load_run
from prepare_data import dedup_by_query, near_dup_filter, stratified_split, validate_labels
from prepare_data import main as prepare_main
from train import main as train_main

LABELS = ["refund", "logistics", "recommend"]
TEMPLATES = {
    "refund": ["我要退款 {i}", "退货退款怎么弄 {i}", "这笔单我想退 {i}", "申请退款服务 {i}"],
    "logistics": ["快递到哪了 {i}", "物流单号查一下 {i}", "什么时候发货 {i}", "包裹到了没有 {i}"],
    "recommend": ["推荐个背包 {i}", "有什么T恤推荐 {i}", "帮我看看露营灯 {i}", "逛逛商城 {i}"],
}


def _synthetic_records(n_per_class: int = 24) -> list[dict]:
    return [
        {"query": tpl.format(i=i), "label": label, "source": "synthetic"}
        for label, tpls in TEMPLATES.items()
        for i in range(n_per_class)
        for tpl in [tpls[i % len(tpls)]]
    ]


def _write_config(tmp_path: Path, data_dir: Path, run_dir: Path) -> Path:
    cfg = f"""
[task]
name = "smoke"
input_field = "query"
label_field = "label"
labels = {json.dumps(LABELS)}

[data]
train_jsonl = "{data_dir / 'labeled.jsonl'}"
out_dir = "{data_dir / 'processed'}"
heldout_ratio = 0.25
near_dup_threshold = 0.90

[model]
encoder = "hash"
device = "cpu"

[train]
epochs = 30
batch_size = 16
lr = 0.05
seed = 42

[output]
run_dir = "{run_dir}"
"""
    path = tmp_path / "smoke.toml"
    path.write_text(cfg, encoding="utf-8")
    return path


class TestAtomic:
    def test_write_json_atomic(self, tmp_path):
        target = tmp_path / "nested" / "m.json"
        write_json_atomic({"a": 1}, target)
        assert json.loads(target.read_text(encoding="utf-8")) == {"a": 1}
        assert not (tmp_path / "nested" / "m.json.tmp").exists()  # tmp 已替换清理
        write_json_atomic({"a": 2}, target)  # 覆盖旧版(逐 epoch 重写路径)
        assert json.loads(target.read_text(encoding="utf-8")) == {"a": 2}


class TestPrepare:
    def test_dedup_keeps_first(self):
        records = [{"query": "退款", "label": "refund"}, {"query": "退款", "label": "refund"}, {"query": "发货", "label": "logistics"}]
        out, removed = dedup_by_query(records)
        assert removed == 1 and len(out) == 2 and out[0] is records[0]

    def test_split_stratified_and_reproducible(self):
        records = _synthetic_records(20)
        train_a, held_a = stratified_split(records, 0.25, seed=7)
        train_b, held_b = stratified_split(records, 0.25, seed=7)
        assert (len(held_a), len(train_a)) == (len(held_b), len(train_b))
        assert {r["label"] for r in held_a} == set(LABELS)  # 分层:每类都有 heldout
        assert {r["query"] for r in train_a} == {r["query"] for r in train_b}  # 同 seed 可复现

    def test_near_dup_filter_drops_blocklist_hits(self):
        records = [{"query": "我要退款 1", "label": "refund"}, {"query": "完全无关的句子", "label": "recommend"}]
        kept, removed = near_dup_filter(records, ["我要退款 1"], "hash", 0.90)
        assert removed == 1 and [r["query"] for r in kept] == ["完全无关的句子"]

    def test_validate_labels_rejects_unknown(self):
        with pytest.raises(SystemExit):
            validate_labels([{"label": "gmv"}], LABELS)

    def test_report_shapes(self):
        report = classification_report([0, 0, 1, 1], [0, 1, 1, 1], ["a", "b"])
        assert report["accuracy"] == 0.75 and report["macro_f1"] > 0
        assert report["per_class"]["a"]["support"] == 2


def _prepare(tmp_path: Path) -> Path:
    """合成数据落盘 + prepare_data 跑完,返回 config 路径(run 目录约定 = tmp_path/"run")。"""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "labeled.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in _synthetic_records()), encoding="utf-8"
    )
    cfg = _write_config(tmp_path, data_dir, tmp_path / "run")
    assert prepare_main(["--config", str(cfg)]) == 0
    return cfg


class TestEndToEnd:
    """prepare → train → evaluate 三连(全程 hash 编码器,秒级)。"""

    def test_full_pipeline(self, tmp_path, capsys):
        cfg = _prepare(tmp_path)
        stats = json.loads((tmp_path / "data" / "processed" / "stats.json").read_text(encoding="utf-8"))
        assert stats["train"] > 0 and stats["heldout"] > 0
        assert set(stats["per_class"]) == set(LABELS)

        assert train_main(["--config", str(cfg)]) == 0
        run_dir = tmp_path / "run"
        assert (run_dir / "head.pt").exists() and (run_dir / "labels.json").exists()
        metrics = json.loads((run_dir / "metrics.json").read_text(encoding="utf-8"))
        assert metrics["heldout"]["accuracy"] >= 0.9  # 合成可分数据,hash 头应近满分

        head, labels, snapshot = load_run(run_dir)
        assert labels == LABELS and snapshot["model"]["encoder"] == "hash"
        import torch

        assert head.weight.shape == (len(LABELS), head.weight.shape[1]) and torch.isfinite(head.weight).all()

    def test_metrics_meta_and_best_epoch(self, tmp_path):
        cfg = _prepare(tmp_path)
        stats = json.loads((tmp_path / "data" / "processed" / "stats.json").read_text(encoding="utf-8"))
        assert train_main(["--config", str(cfg)]) == 0
        run_dir = tmp_path / "run"
        metrics = json.loads((run_dir / "metrics.json").read_text(encoding="utf-8"))

        assert {"train", "heldout", "loss_curve"} <= set(metrics)  # 三旧键原样(向后兼容)
        meta = metrics["meta"]
        assert meta["completed"] is True
        assert meta["train_samples"] == stats["train"] and meta["heldout_samples"] == stats["heldout"]
        assert meta["encoder"] == "hash"
        assert meta["started_at"] and meta["duration_seconds"] is not None
        assert meta["git_commit"] is None or len(meta["git_commit"]) == 40  # 仓库内跑有 hash,CI 外无 git 时 None

        # best_epoch 与 loss_curve 逐项一致(严格大于取最早最大,与训练内克隆同规则)
        curve = metrics["loss_curve"]
        best_acc = max(e["heldout_acc"] for e in curve if "heldout_acc" in e)
        first_best = next(e["epoch"] for e in curve if e.get("heldout_acc") == best_acc)
        assert meta["best_epoch"] == first_best and meta["best_heldout_acc"] == best_acc

    def test_curve_html_generated(self, tmp_path):
        cfg = _prepare(tmp_path)
        assert train_main(["--config", str(cfg)]) == 0
        run_dir = tmp_path / "run"
        page = (run_dir / "curve.html").read_text(encoding="utf-8")  # train.py 收尾自动生成
        assert "<svg" in page and "train_loss" in page and "heldout 准确率" in page
        assert not list(run_dir.glob("*.tmp"))  # 原子写无半截文件残留


class TestCrashFlush:
    """训练中途被杀:已跑 epoch 的曲线必须已在盘上(meta.completed=False 标记残局)。"""

    def test_partial_metrics_survive_crash(self, tmp_path, monkeypatch):
        cfg = _prepare(tmp_path)
        real_flush = train._flush_partial
        calls = {"n": 0}

        def flaky_flush(run_dir, meta, curve):
            calls["n"] += 1
            if calls["n"] >= 2:
                raise SystemExit("[Test] 模拟训练中途被杀")
            real_flush(run_dir, meta, curve)

        monkeypatch.setattr(train, "_flush_partial", flaky_flush)
        with pytest.raises(SystemExit):
            train_main(["--config", str(cfg)])

        metrics = json.loads((tmp_path / "run" / "metrics.json").read_text(encoding="utf-8"))
        assert metrics["meta"]["completed"] is False
        assert [e["epoch"] for e in metrics["loss_curve"]] == [1]  # 第 1 epoch 已 flush,未蒸发


class TestPlot:
    def test_build_svg_single_epoch(self):
        svg = plot_curve.build_svg([{"epoch": 1, "train_loss": 0.5, "heldout_acc": 0.9}], title="t", subtitle="s")
        assert "<svg" in svg and "<circle" in svg  # 单点以圆点标记保证可见
        flat = plot_curve.build_svg(
            [{"epoch": 1, "train_loss": 2.0, "heldout_acc": 0.9}, {"epoch": 2, "train_loss": 2.0, "heldout_acc": 0.9}],
            title="t",
            subtitle="s",
        )
        assert "2.00" in flat  # 等值退化落中线,不炸不除零

    def test_build_svg_without_heldout(self):
        svg = plot_curve.build_svg([{"epoch": 1, "train_loss": 1.0}], title="t", subtitle="s")
        assert "无 heldout 评估" in svg
        assert 'stroke="#10b981"' not in svg  # 无评估带不渲染曲线/参考线

    def test_cli_standalone(self, tmp_path, capsys):
        cfg = _prepare(tmp_path)
        assert train_main(["--config", str(cfg)]) == 0
        run_dir = tmp_path / "run"
        (run_dir / "curve.html").unlink()
        assert plot_curve.main(["--run-dir", str(run_dir)]) == 0  # 对现存 run 独立重生成
        assert (run_dir / "curve.html").exists()
