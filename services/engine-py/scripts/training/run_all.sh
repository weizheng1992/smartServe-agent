#!/usr/bin/env bash
# metric_head 一键训练(词表种子 → 数据准备 → 训练 → 评估)
set -euo pipefail
cd "$(dirname "$0")/../.."
# 模型下载走国内镜像(可与 .env 的 HF_ENDPOINT 保持一致)
export HF_ENDPOINT="https://hf-mirror.com"

# 全程日志归档:逐条命令与输出 tee 落盘(-o pipefail 保住 set -e 穿透 tee;
# 日志目录已 gitignore,事后可回溯某次跑的 stats/loss 数值)
LOG_DIR="training_runs/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/train_$(date +%Y%m%d_%H%M%S).log"
log() { echo "$*" | tee -a "$LOG_FILE"; }
run_logged() {
  log "+ $*"
  "$@" 2>&1 | tee -a "$LOG_FILE"
}

log "① 词表弱标注种子"
run_logged uv run python scripts/training/seed_from_registry.py --out training_data/metric_head/seed.jsonl

log "② 数据准备"
run_logged uv run python scripts/training/prepare_data.py --config scripts/training/configs/metric_head.toml

log "③ 训练"
run_logged uv run python scripts/training/train.py --config scripts/training/configs/metric_head.toml

log "④ 评估"
run_logged uv run python scripts/training/evaluate.py --run-dir training_runs/metric_head \
  --data training_data/metric_head/processed/heldout.jsonl

log ""
log "=== metric_head 训练完成,产物: training_runs/metric_head/(日志: $LOG_FILE)==="
