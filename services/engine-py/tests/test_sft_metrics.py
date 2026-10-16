"""SFT 过程监控单测(callback + run_summary;fake state 直调,零 trl/DB/网络)。

sft_metrics.py 刻意只依赖标准库 + transformers:本地 venv 无 trl/peft,
TRL TrainerCallback 的钩子协议用 fake state(SimpleNamespace)即可钉死。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

TRAINING_DIR = Path(__file__).resolve().parents[1] / "scripts" / "training"
sys.path.insert(0, str(TRAINING_DIR))

from sft_metrics import SftMetricsCallback, build_run_summary, write_json_atomic


def _state(steps: int = 10, max_steps: int = 100, **extra) -> SimpleNamespace:
    log_history = [
        {"loss": 1.38, "learning_rate": 2e-4, "epoch": 0.06, "step": 10},
        {"loss": 0.42, "learning_rate": 2e-4, "epoch": 0.12, "step": 20},
    ]
    return SimpleNamespace(global_step=steps, max_steps=max_steps, log_history=log_history, **extra)


class TestAtomicWrite:
    def test_replaces_and_cleans_tmp(self, tmp_path):
        target = tmp_path / "metrics.json"
        write_json_atomic({"v": 1}, target)
        assert json.loads(target.read_text(encoding="utf-8")) == {"v": 1}
        assert not (tmp_path / "metrics.json.tmp").exists()
        write_json_atomic({"v": 2}, target)
        assert json.loads(target.read_text(encoding="utf-8")) == {"v": 2}


class TestSftMetricsCallback:
    def test_on_log_writes_log_history(self, tmp_path):
        cb = SftMetricsCallback(tmp_path)
        state = _state()
        cb.on_log(args=None, state=state, control=None)
        payload = json.loads((tmp_path / "metrics.json").read_text(encoding="utf-8"))
        assert payload["meta"] == {"current_step": 10, "max_steps": 100, "completed": False}
        assert payload["log_history"] == state.log_history  # 截至当前步的完整快照

    def test_on_train_end_marks_completed(self, tmp_path):
        cb = SftMetricsCallback(tmp_path)
        cb.on_train_end(args=None, state=_state(), control=None)
        payload = json.loads((tmp_path / "metrics.json").read_text(encoding="utf-8"))
        assert payload["meta"]["completed"] is True

    def test_empty_log_history_tolerated(self, tmp_path):
        cb = SftMetricsCallback(tmp_path)
        cb.on_log(args=None, state=SimpleNamespace(global_step=0, max_steps=100, log_history=[]), control=None)
        payload = json.loads((tmp_path / "metrics.json").read_text(encoding="utf-8"))
        assert payload["log_history"] == []


class TestBuildRunSummary:
    def test_extracts_runtime_and_fallback_loss(self):
        state = _state()
        state.log_history.append({"train_runtime": 8482.413, "train_samples_per_second": 1.58, "epoch": 3.0, "train_loss": 0.0123})
        summary = build_run_summary(state, dataset_size=4478, num_train_epochs=3)
        assert summary["completed"] is True
        assert summary["final_loss"] == 0.0123  # 总结行的 train_loss
        assert summary["train_loss"] == 0.0123
        assert summary["train_runtime_seconds"] == 8482.41
        assert summary["samples_per_second"] == 1.58
        assert summary["epoch"] == 3.0 and summary["global_step"] == 10
        assert summary["dataset_size"] == 4478 and summary["num_train_epochs"] == 3
        assert summary["written_at"]

    def test_prefers_state_train_loss(self):
        state = _state()
        state.train_loss = 0.0119  # state 属性优先于逐 logging 步末条
        summary = build_run_summary(state)
        assert summary["train_loss"] == 0.0119
        assert summary["final_loss"] is None  # 无总结行 → 无 train_runtime/final_loss

    def test_fallback_last_logged_loss(self):
        state = _state()  # 无 train_loss 属性 → 回退 log_history 末条 loss(近似口径)
        summary = build_run_summary(state)
        assert summary["train_loss"] == 0.42

    def test_empty_history_all_null(self):
        summary = build_run_summary(SimpleNamespace(global_step=0, max_steps=0, log_history=[]))
        assert summary["final_loss"] is None and summary["train_loss"] is None
        assert summary["train_runtime_seconds"] is None and summary["completed"] is True
