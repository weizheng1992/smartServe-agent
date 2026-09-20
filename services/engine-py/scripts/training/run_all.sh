#!/usr/bin/env bash
# metric_head 一键训练(词表种子 → 数据准备 → 训练 → 评估)
set -e
cd "$(dirname "$0")/../.."
# 模型下载走国内镜像(可与 .env 的 HF_ENDPOINT 保持一致)
export HF_ENDPOINT="https://hf-mirror.com"

echo "① 词表弱标注种子"
uv run python scripts/training/seed_from_registry.py --out training_data/metric_head/seed.jsonl

echo "② 数据准备"
uv run python scripts/training/prepare_data.py --config scripts/training/configs/metric_head.toml

echo "③ 训练"
uv run python scripts/training/train.py --config scripts/training/configs/metric_head.toml

echo "④ 评估"
uv run python scripts/training/evaluate.py --config scripts/training/configs/metric_head.toml

echo ""
echo "=== metric_head 训练完成,产物: training_runs/metric_head/ ==="
