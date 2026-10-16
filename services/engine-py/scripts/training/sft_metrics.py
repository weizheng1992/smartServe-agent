"""SFT 训练过程监控(callback + 摘要;零 trl/peft 依赖,本地可单测)。

背景(2026-10-16 审计):SFT 轨此前只有 TRL 控制台 stdout(report_to=[]),
loss 曲线只存在于 pai-dsw 实录的人工抄录,不可机读、不可复绘。本模块补两件:
① SftMetricsCallback —— 每 logging_steps 把 trainer 的 log_history 原子写
   output_dir/metrics.json(崩溃时已跑部分保留 = 过程监控本体);
② build_run_summary —— 训练结束取最终 loss/train_runtime 落 run_summary.json
   (补 pai-dsw 文档「把最终 loss/train_runtime 记下来」未兑现的承诺,机器可读版)。

依赖纪律:只 import 标准库 + transformers(本地 venv 已有);trl/peft 相关全部
留在 sft_train.py 的延迟导入区 —— 本模块的测试用 fake state 直调,不装训练栈。
原子写与 common.write_json_atomic 同款(tmp + os.replace),刻意自包含一份以
守住「只 transformers」边界(各 4 行,注释互指)。
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from transformers import TrainerCallback


def write_json_atomic(payload: dict[str, Any], path: str | Path) -> None:
    """JSON 原子写:tmp 落盘后 os.replace 整体替换(见 common.write_json_atomic)。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


class SftMetricsCallback(TrainerCallback):
    """把 trainer.log_history 逐 logging_steps 落盘(TRL 控制台日志的机器可读版)。

    on_log 按 logging_steps(当前 10)触发,metrics.json 始终是「截至当前步」的
    完整快照;on_train_end 定稿 completed=True。中途崩溃/被杀时盘上最后一份即
    残局现场 —— 与 metric head 轨 train.py 的逐 epoch flush 同一纪律。
    """

    def __init__(self, out_dir: str | Path) -> None:
        self._path = Path(out_dir) / "metrics.json"

    def _dump(self, state: Any, *, completed: bool) -> None:
        write_json_atomic(
            {
                "meta": {
                    "current_step": getattr(state, "global_step", None),
                    "max_steps": getattr(state, "max_steps", None),
                    "completed": completed,
                },
                "log_history": list(getattr(state, "log_history", []) or []),
            },
            self._path,
        )

    def on_log(self, args: Any, state: Any, control: Any, logs: dict | None = None, **kwargs: Any) -> None:
        self._dump(state, completed=False)

    def on_train_end(self, args: Any, state: Any, control: Any, **kwargs: Any) -> None:
        self._dump(state, completed=True)


def build_run_summary(
    state: Any,
    *,
    dataset_size: int | None = None,
    num_train_epochs: float | None = None,
) -> dict[str, Any]:
    """从 trainer.state 提炼训练终局摘要(纯函数;fake state 直调可测)。

    取数规则:log_history 末条含 train_runtime 的行 = train() 的总结行;
    train_loss 三级回退:state 属性 → 总结行 train_loss → 逐 logging 步末条
    loss(近似,与 pai-dsw 抄录口径一致);缺什么记 null,不臆造。
    """
    hist = list(getattr(state, "log_history", []) or [])
    final = next((h for h in reversed(hist) if "train_runtime" in h), {})
    losses = [h["loss"] for h in hist if "loss" in h]
    train_loss = getattr(state, "train_loss", None)
    if train_loss is None and "train_loss" in final:
        train_loss = final["train_loss"]
    if train_loss is None and losses:
        train_loss = losses[-1]
    return {
        "completed": True,
        "written_at": datetime.now().isoformat(timespec="seconds"),
        "global_step": getattr(state, "global_step", None),
        "max_steps": getattr(state, "max_steps", None),
        "epoch": final.get("epoch"),
        "final_loss": final.get("train_loss"),
        "train_loss": round(train_loss, 6) if isinstance(train_loss, float) else train_loss,
        "train_runtime_seconds": round(final["train_runtime"], 2) if "train_runtime" in final else None,
        "samples_per_second": final.get("train_samples_per_second"),
        "dataset_size": dataset_size,
        "num_train_epochs": num_train_epochs,
    }
