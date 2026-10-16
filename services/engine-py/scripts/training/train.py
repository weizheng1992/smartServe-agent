"""config 驱动的闭集分类头训练(三缝之①意图分类头 / ②指标映射分类头的模型侧产物)。

形态 = embedding + torch 线性头(11-D3「SetFit 式」的零新依赖实现):encoder 用
sentence-transformers(bge 与线上判重缓存同底座),头为单层 Linear,CPU 分钟级。
输出 run 目录 = 未来 adapter 的全部载荷::

    <run_dir>/head.pt             线性头 state_dict(heldout 最优 epoch 的权重)
    <run_dir>/labels.json         闭集标签序(推理 argmax 索引即此序)
    <run_dir>/config.snapshot.toml 训练配置快照(evaluate/接入侧据此加载 encoder)
    <run_dir>/metrics.json        train/heldout 指标 + loss_curve + 运行元数据(meta)
    <run_dir>/curve.html          训练曲线页(plot_curve 自动生成,浏览器可开)

监控纪律(训练过程可观测):逐 epoch stderr 进度行 + loss_curve 经
write_json_atomic 逐 epoch flush(中途崩溃已跑 epoch 的曲线不丢,meta.completed
=false 即残局标记);最终 metrics.json 含运行元数据(时间戳/样本数/git hash)。
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import torch
from common import (
    classification_report,
    encode_texts,
    get_encoder,
    load_config,
    load_jsonl,
    write_json_atomic,
)
from torch import nn


def train_linear_head(
    embeddings: torch.Tensor,
    label_idx: list[int],
    num_classes: int,
    *,
    epochs: int,
    batch_size: int,
    lr: float,
    seed: int,
    eval_each_epoch: tuple[torch.Tensor, list[int]] | None = None,
    on_epoch: Callable[[dict], None] | None = None,
) -> tuple[nn.Linear, list[dict]]:
    """小批量 CE 训练单层线性头;全量放内存(闭集分类头数据量级 = 千句级,CPU 足够)。

    返回 (head, curve):curve = 每 epoch 的 train_loss / heldout_accuracy(如有评估集)
    —— 损失曲线落 metrics.json,前端可渲染训练图(18/10 号图表语义的复用)。

    on_epoch(entry) 在每 epoch 收尾时同步回调(调用方做进度打印 + 曲线 flush)。
    best-epoch 择优:heldout_acc 严格大于历史最高时克隆权重(并列取最早 epoch),
    循环结束回装最优 —— 无评估集则无择优,退化返回最终权重。
    """
    torch.manual_seed(seed)
    dim = embeddings.shape[1]
    head = nn.Linear(dim, num_classes)
    opt = torch.optim.Adam(head.parameters(), lr=lr)
    loss_fn = nn.CrossEntropyLoss()
    curve: list[dict] = []
    eval_emb, eval_idx = eval_each_epoch if eval_each_epoch else (None, None)
    best_acc = -1.0
    best_state: dict | None = None
    for epoch in range(epochs):
        epoch_losses = []
        perm = torch.randperm(len(embeddings))
        for start in range(0, len(perm), batch_size):
            batch = perm[start : start + batch_size]
            opt.zero_grad()
            logits = head(embeddings[batch])
            target = torch.tensor([label_idx[i] for i in batch.tolist()])
            loss = loss_fn(logits, target)
            loss.backward()
            opt.step()
            epoch_losses.append(float(loss.detach()))
        entry = {"epoch": epoch + 1, "train_loss": round(sum(epoch_losses) / len(epoch_losses), 4)}
        if eval_emb is not None:
            with torch.no_grad():
                pred = head(eval_emb).argmax(dim=1)
                correct = int((pred == torch.tensor(eval_idx)).sum())
            entry["heldout_acc"] = round(correct / max(len(eval_idx), 1), 4)
            # 择优克隆(与 main 里 meta.best_epoch 的推导同比较符:严格大于)
            if entry["heldout_acc"] > best_acc:
                best_acc = entry["heldout_acc"]
                best_state = {k: v.detach().clone() for k, v in head.state_dict().items()}
        curve.append(entry)
        if on_epoch is not None:
            on_epoch(entry)
    if best_state is not None:
        head.load_state_dict(best_state)
    return head, curve


def _git_commit() -> str | None:
    """当前 git commit(产物溯源用);非 git 环境 / 无 git / 超时一律 None。"""
    try:
        proc = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=5, check=False)
    except Exception:
        return None
    out = (proc.stdout or "").strip()
    if proc.returncode == 0 and len(out) == 40:
        return out
    return None


def _flush_partial(run_dir: Path, meta: dict, curve: list[dict]) -> None:
    """逐 epoch 落部分指标(meta.completed=False;中途崩溃曲线不丢)。模块级供测试打桩。"""
    write_json_atomic({"meta": {**meta, "completed": False}, "loss_curve": curve}, run_dir / "metrics.json")


@torch.no_grad()
def predict(head: nn.Linear, embeddings: torch.Tensor) -> tuple[list[int], list[float]]:
    """argmax 标签 + softmax 置信度(缝契约的「闭集标签 + 置信度」输出)。"""
    probs = torch.softmax(head(embeddings), dim=1)
    conf, pred = probs.max(dim=1)
    return pred.tolist(), conf.tolist()


def _load_split(data_cfg: dict, split: str, labels: list[str]) -> tuple[list[str], list[int]]:
    records = load_jsonl(Path(data_cfg["out_dir"]) / f"{split}.jsonl")
    unknown = sorted({r["label"] for r in records} - set(labels))
    if unknown:
        raise SystemExit(f"[Train] {split}.jsonl 存在闭集外标签 {unknown};先跑 prepare_data.py")
    return [r["query"] for r in records], [labels.index(r["label"]) for r in records]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="训练闭集分类头(embedding + 线性头)")
    parser.add_argument("--config", required=True, help="训练配置 TOML")
    args = parser.parse_args(argv)

    cfg = load_config(args.config)
    task, data, model, tcfg = cfg["task"], cfg["data"], cfg["model"], cfg["train"]
    labels: list[str] = task["labels"]
    epochs = tcfg.get("epochs", 20)

    train_texts, train_idx = _load_split(data, "train", labels)
    if not train_texts:
        raise SystemExit("[Train] train.jsonl 为空;先跑 prepare_data.py")
    heldout_texts, heldout_idx = _load_split(data, "heldout", labels)

    device = model.get("device", "cpu")
    print(f"[Train] encoder={model['encoder']} device={device} train={len(train_texts)} heldout={len(heldout_texts)}", file=sys.stderr)
    encoder = get_encoder(model["encoder"], device=device)
    train_emb = encode_texts(encoder, train_texts, batch_size=tcfg.get("batch_size", 32))
    heldout_emb = encode_texts(encoder, heldout_texts, batch_size=tcfg.get("batch_size", 32)) if heldout_texts else None

    started_at = datetime.now().isoformat(timespec="seconds")
    started = time.perf_counter()

    # run 目录与溯源产物提前写:训练中途崩溃也留得下 labels/快照(head.pt 缺失时
    # 接入侧 get_metric_head 按存在性降级不启用,无脏读面)。
    run_dir = Path(cfg["output"]["run_dir"])
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "labels.json").write_text(json.dumps({"labels": labels, "encoder": model["encoder"]}, ensure_ascii=False, indent=2), encoding="utf-8")
    shutil.copyfile(args.config, run_dir / "config.snapshot.toml")

    meta: dict = {
        "started_at": started_at,
        "duration_seconds": None,
        "train_samples": len(train_texts),
        "heldout_samples": len(heldout_texts),
        "encoder": model["encoder"],
        "git_commit": _git_commit(),
        "best_epoch": None,
        "best_heldout_acc": None,
        "completed": False,
    }
    curve: list[dict] = []

    def _on_epoch(entry: dict) -> None:
        # 每 epoch 进度行 + 曲线 flush(原子写;崩溃后 metrics.json 保留已跑部分)
        curve.append(entry)
        held = f" heldout_acc={entry['heldout_acc']}" if "heldout_acc" in entry else ""
        print(f"[Train] epoch {entry['epoch']}/{epochs} train_loss={entry['train_loss']}{held}", file=sys.stderr)
        _flush_partial(run_dir, meta, curve)

    eval_pair = (heldout_emb, heldout_idx) if heldout_emb is not None and heldout_idx else None
    head, curve = train_linear_head(
        train_emb, train_idx, len(labels),
        epochs=epochs, batch_size=tcfg.get("batch_size", 32),
        lr=tcfg.get("lr", 0.01), seed=tcfg.get("seed", 42),
        eval_each_epoch=eval_pair,
        on_epoch=_on_epoch,
    )

    # best 推导与 train_linear_head 内克隆同规则:严格大于,并列取最早 epoch
    best_entries = [e for e in curve if "heldout_acc" in e]
    if best_entries:
        best = max(best_entries, key=lambda e: e["heldout_acc"])
        meta["best_epoch"] = best["epoch"]
        meta["best_heldout_acc"] = best["heldout_acc"]
    else:
        meta["best_epoch"] = len(curve)
    meta["duration_seconds"] = round(time.perf_counter() - started, 2)
    meta["completed"] = True

    torch.save(head.state_dict(), run_dir / "head.pt")

    # 分类报告在回装最优权重后的 head 上算:入库报告与入库权重自洽
    pred_idx, _ = predict(head, train_emb)
    metrics = {"train": classification_report(train_idx, pred_idx, labels)}
    if heldout_emb is not None:
        pred_idx, _ = predict(head, heldout_emb)
        metrics["heldout"] = classification_report(heldout_idx, pred_idx, labels)
    metrics["loss_curve"] = curve
    metrics["meta"] = meta
    write_json_atomic(metrics, run_dir / "metrics.json")

    # 曲线页自动生成(渲染失败不影响训练产物,重训后曲线不再陈旧)
    try:
        import plot_curve

        plot_curve.write_curve_html(run_dir)
    except Exception as plot_err:
        print(f"[Train] 曲线渲染失败(不影响产物): {plot_err}", file=sys.stderr)

    held = metrics.get("heldout", {}).get("accuracy")
    print(
        f"[Train] 完成 → {run_dir}(heldout accuracy={held if held is not None else 'N/A,样本不足'}"
        f" best_epoch={meta['best_epoch']} 耗时={meta['duration_seconds']}s)",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
