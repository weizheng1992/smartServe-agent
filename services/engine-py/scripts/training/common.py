"""训练脚手架公共件(11 号票「训练方案模板」的代码化)。

被 prepare_data / train / evaluate 按同目录模块复用(CLI 直跑时脚本目录即在
sys.path;测试经 sys.path 注入)。刻意零新增依赖:torch 与 sentence-transformers
为 engine 既有依赖,配置读取用 py312 标准库 tomllib。

三缝接入契约(训练产物即 adapter 的载荷):
- 意图分类头缝(IntentScorer):labels = 意图闭集
- 指标映射分类头缝(MetricQueryEngine.resolve 前端):labels = 指标键闭集
- 判重缓存换模缝:仅换 encoder 权重路径,不走本模块的分类头
统一输出形态「问句 → 闭集标签 + 置信度」,模型即 adapter(回滚 = 配置回退)。
"""

from __future__ import annotations

import json
import tomllib
from pathlib import Path
from typing import Any

import torch

DEFAULT_HASH_DIM = 256


def load_config(path: str | Path) -> dict[str, Any]:
    """读 TOML 训练配置(用户唯一要改的东西;相对路径按 CWD=services/engine-py 解析)。"""
    with open(path, "rb") as f:
        return tomllib.load(f)


def load_jsonl(path: str | Path) -> list[dict[str, Any]]:
    records = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def write_jsonl(records: list[dict[str, Any]], path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, ensure_ascii=False, default=str) + "\n" for r in records), encoding="utf-8")


class HashEncoder:
    """确定性字符 n-gram 哈希编码器(冒烟/CI 用:不下载模型、结果可复现)。

    真实训练用 [model].encoder = "BAAI/bge-small-zh-v1.5"(与线上判重缓存同底座);
    "hash" 仅保证流水线端到端可测,不代表语义质量。
    """

    def __init__(self, dim: int = DEFAULT_HASH_DIM, ngram: int = 3) -> None:
        self.dim = dim
        self.ngram = ngram

    def _vector(self, text: str) -> torch.Tensor:
        vec = torch.zeros(self.dim, dtype=torch.float32)
        text = text.strip()
        for i in range(max(1, len(text) - self.ngram + 1)):
            gram = text[i : i + self.ngram] if len(text) >= self.ngram else text
            vec[hash(gram) % self.dim] += 1.0
        norm = vec.norm()
        return vec / norm if norm > 0 else vec

    def encode(self, texts: list[str], batch_size: int = 64, **_: Any) -> torch.Tensor:
        return torch.stack([self._vector(t) for t in texts])


def get_encoder(name: str, device: str = "cpu"):
    """编码器工厂:name="hash" → 冒烟编码器;否则按 sentence-transformers 模型名加载。"""
    if name == "hash":
        return HashEncoder()
    # 训练脚本不走 llm/chat.py,这里补镜像(与 .env 保持一致)
    import os

    os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(name, device=device)


def encode_texts(encoder: Any, texts: list[str], batch_size: int = 64) -> torch.Tensor:
    """统一编码出口:sentence-transformers 返回 ndarray,这里归一为 l2-norm 的 float32 Tensor。"""
    out = encoder.encode(texts, batch_size=batch_size)
    if not isinstance(out, torch.Tensor):
        out = torch.from_tensor(out) if hasattr(out, "__tensor__") else torch.tensor(out)
    out = out.to(torch.float32)
    norms = out.norm(dim=1, keepdim=True)
    return out / norms.clamp_min(1e-12)


def cosine_matrix(a: torch.Tensor, b: torch.Tensor) -> torch.Tensor:
    """两两余弦(输入应为 l2 归一后的向量)。"""
    return a @ b.t()


def classification_report(y_true: list[int], y_pred: list[int], label_names: list[str]) -> dict[str, Any]:
    """每类 P/R/F1 + macro + accuracy(评测口径与 promptfoo intentF1 的单类 F1 对齐)。"""
    n = len(label_names)
    tp = [0] * n
    fp = [0] * n
    fn = [0] * n
    correct = 0
    for t, p in zip(y_true, y_pred, strict=True):
        if t == p:
            tp[t] += 1
            correct += 1
        else:
            fp[p] += 1
            fn[t] += 1
    per_class = {}
    f1s = []
    for i, name in enumerate(label_names):
        precision = tp[i] / (tp[i] + fp[i]) if tp[i] + fp[i] else 0.0
        recall = tp[i] / (tp[i] + fn[i]) if tp[i] + fn[i] else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        f1s.append(f1)
        per_class[name] = {"precision": round(precision, 4), "recall": round(recall, 4), "f1": round(f1, 4), "support": tp[i] + fn[i]}
    return {
        "accuracy": round(correct / len(y_true), 4) if y_true else 0.0,
        "macro_f1": round(sum(f1s) / n, 4) if n else 0.0,
        "per_class": per_class,
    }
