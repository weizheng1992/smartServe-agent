"""config 驱动的闭集分类头训练(三缝之①意图分类头 / ②指标映射分类头的模型侧产物)。

形态 = embedding + torch 线性头(11-D3「SetFit 式」的零新依赖实现):encoder 用
sentence-transformers(bge 与线上判重缓存同底座),头为单层 Linear,CPU 分钟级。
输出 run 目录 = 未来 adapter 的全部载荷::

    <run_dir>/head.pt             线性头 state_dict
    <run_dir>/labels.json         闭集标签序(推理 argmax 索引即此序)
    <run_dir>/config.snapshot.toml 训练配置快照(evaluate/接入侧据此加载 encoder)
    <run_dir>/metrics.json        train/heldout 指标(每类 P/R/F1)

用法::

    uv run python scripts/training/train.py --config scripts/training/configs/metric_head.toml
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import torch
from common import classification_report, encode_texts, get_encoder, load_config, load_jsonl
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
) -> tuple[nn.Linear, list[dict]]:
    """小批量 CE 训练单层线性头;全量放内存(闭集分类头数据量级 = 千句级,CPU 足够)。

    返回 (head, curve):curve = 每 epoch 的 train_loss / heldout_accuracy(如有评估集)
    —— 损失曲线落 metrics.json,前端可渲染训练图(18/10 号图表语义的复用)。
    """
    torch.manual_seed(seed)
    dim = embeddings.shape[1]
    head = nn.Linear(dim, num_classes)
    opt = torch.optim.Adam(head.parameters(), lr=lr)
    loss_fn = nn.CrossEntropyLoss()
    curve: list[dict] = []
    eval_emb, eval_idx = eval_each_epoch if eval_each_epoch else (None, None)
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
        curve.append(entry)
    return head, curve


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

    train_texts, train_idx = _load_split(data, "train", labels)
    if not train_texts:
        raise SystemExit("[Train] train.jsonl 为空;先跑 prepare_data.py")
    heldout_texts, heldout_idx = _load_split(data, "heldout", labels)

    device = model.get("device", "cpu")
    print(f"[Train] encoder={model['encoder']} device={device} train={len(train_texts)} heldout={len(heldout_texts)}", file=sys.stderr)
    encoder = get_encoder(model["encoder"], device=device)
    train_emb = encode_texts(encoder, train_texts, batch_size=tcfg.get("batch_size", 32))
    heldout_emb = encode_texts(encoder, heldout_texts, batch_size=tcfg.get("batch_size", 32)) if heldout_texts else None

    eval_pair = (heldout_emb, heldout_idx) if heldout_emb is not None and heldout_idx else None
    head, curve = train_linear_head(
        train_emb, train_idx, len(labels),
        epochs=tcfg.get("epochs", 20), batch_size=tcfg.get("batch_size", 32),
        lr=tcfg.get("lr", 0.01), seed=tcfg.get("seed", 42),
        eval_each_epoch=eval_pair,
    )

    run_dir = Path(cfg["output"]["run_dir"])
    run_dir.mkdir(parents=True, exist_ok=True)
    torch.save(head.state_dict(), run_dir / "head.pt")
    (run_dir / "labels.json").write_text(json.dumps({"labels": labels, "encoder": model["encoder"]}, ensure_ascii=False, indent=2), encoding="utf-8")
    shutil.copyfile(args.config, run_dir / "config.snapshot.toml")

    pred_idx, _ = predict(head, train_emb)
    metrics = {"train": classification_report(train_idx, pred_idx, labels)}
    if heldout_emb is not None:
        pred_idx, _ = predict(head, heldout_emb)
        metrics["heldout"] = classification_report(heldout_idx, pred_idx, labels)
    metrics["loss_curve"] = curve
    (run_dir / "metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")

    held = metrics.get("heldout", {}).get("accuracy")
    print(f"[Train] 完成 → {run_dir}(heldout accuracy={held if held is not None else 'N/A,样本不足'})", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
