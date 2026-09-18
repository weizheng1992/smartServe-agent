"""指标映射分类头 adapter(11-D1 缝②;训练产物 training_runs/<name> 的推理侧)。

契约:问句 → 闭集标签 + 置信度。加载 run 目录四件(labels.json / head.pt /
config.snapshot.toml;encoder 名从快照读,保证与训练同分布)。

三态由 AI_METRIC_HEAD 控制(get_metric_head 工厂在 llm/chat):
- 空/anchor:不启用(纯 L0+L3 现状)
- shadow:并行打分只记日志,不改判定(影子跑对比期)
- on:L0 未命中处插分类头结果,低置信仍放行 L3 —— 11-D1「模型即 adapter」

回滚 = 移除环境变量(不改编排)。encoder 加载懒执行;进程内单例由工厂
lru_cache 保证,与判重缓存共享同一 bge 底座时无额外大内存。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


class MetricHead:
    def __init__(self, run_dir: str | Path) -> None:
        run = Path(run_dir)
        self.labels: list[str] = json.loads((run / "labels.json").read_text(encoding="utf-8"))["labels"]
        import torch
        from torch import nn

        state = torch.load(run / "head.pt", map_location="cpu")
        dim = state["weight"].shape[1]
        self.head: nn.Module = nn.Linear(dim, len(self.labels))
        self.head.load_state_dict(state)
        self.head.eval()
        self.encoder_name: str = json.loads((run / "labels.json").read_text(encoding="utf-8")).get(
            "encoder"
        ) or "BAAI/bge-small-zh-v1.5"
        self._encoder: Any = None  # 懒加载(首个请求才触 torch/模型权重)

    def _encode(self, texts: list[str]):
        if self._encoder is None:
            # 本地缓存优先(与 llm/chat.get_embedding_model 同策略):线上
            # HF 不可达时不允许结算链挂起 —— 失败即响亮抛错走 L3
            import os

            from sentence_transformers import SentenceTransformer

            os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
            try:
                self._encoder = SentenceTransformer(
                    self.encoder_name, device="cpu", local_files_only=True
                )
            except Exception:
                self._encoder = SentenceTransformer(self.encoder_name, device="cpu")
        out = self._encoder.encode(texts)
        import torch

        t = out if isinstance(out, torch.Tensor) else torch.tensor(out)
        t = t.to(torch.float32)
        return t / t.norm(dim=1, keepdim=True).clamp_min(1e-12)

    def predict(self, question: str) -> tuple[str, float]:
        """问句 → (闭集标签, 置信度)。低置信标签交回调用方决策。"""
        import torch

        with torch.no_grad():
            emb = self._encode([question])
            probs = torch.softmax(self.head(emb), dim=1)[0]
        conf, idx = probs.max(dim=0)
        return self.labels[int(idx)], float(conf)


def get_metric_head() -> MetricHead | None:
    """按 AI_METRIC_HEAD 三态返回 adapter 实例;工厂带模式供 resolve 分支判断。"""
    mode = os.environ.get("AI_METRIC_HEAD", "").strip().lower()
    if mode not in ("shadow", "on"):
        return None
    run_dir = os.environ.get("AI_METRIC_HEAD_DIR", "training_runs/metric_head")
    if not (Path(run_dir) / "head.pt").exists():
        print(f"[MetricHead] AI_METRIC_HEAD={mode} 但产物缺失: {run_dir} —— 响亮降级为不启用")
        return None
    try:
        return MetricHead(run_dir)
    except Exception as err:
        print(f"[MetricHead] 加载失败({err}),降级为不启用")
        return None
