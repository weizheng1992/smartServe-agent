"""QLoRA SFT 训练(标准栈:transformers + peft + trl)。

任务:问句 + 指标闭集目录 → SemQL JSON(模型只学语义理解,永不写 SQL,
铁律 08-D1)。数据由 sft_dataset.py 构建(评测集纯门永不入训)。

不用 unsloth:其加载层会向 trainer 注入词表外 eos 占位符('<EOS_TOKEN>'),
trl 校验必挂;标准栈时长约多一半,在免费计算时额度内可忽略。

配置:--config 传 YAML(值作默认,显式 CLI 参数覆盖);
推荐 configs/sft_semql.yaml(2026-09-20 首训实录提取)。

用法(services/engine-py 下)::

    uv run python scripts/training/sft_train.py \\
        --config scripts/training/configs/sft_semql.yaml \\
        --dataset training_data/sft/train.jsonl \\
        --out training_data/sft/adapter

依赖::

    uv pip install trl peft bitsandbytes datasets accelerate
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

DEFAULT_BASE = "Qwen/Qwen2.5-7B-Instruct"
MAX_SEQ_LEN = 2048
EOS = "<|im_end|>"  # Qwen2.5-Instruct 真实结束符;写字面量,不读 tokenizer 运行时值

DEFAULT_LORA = {
    "r": 16,
    "lora_alpha": 32,           # 惯例 = 2×r
    "lora_dropout": 0.05,
    "task_type": "CAUSAL_LM",
    "target_modules": ["q_proj", "k_proj", "v_proj", "o_proj",
                       "gate_proj", "up_proj", "down_proj"],
}


def main(argv: list[str] | None = None) -> int:
    # 两段解析:先取 --config(YAML 值作默认),再以显式 CLI 参数覆盖
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--config", help="YAML 配置文件,值作默认;显式 CLI 参数覆盖之")
    cfg_args, rest = pre.parse_known_args(argv)

    cfg: dict = {}
    if cfg_args.config:
        import yaml
        cfg = yaml.safe_load(Path(cfg_args.config).read_text(encoding="utf-8")) or {}

    lora = {**DEFAULT_LORA, **(cfg.get("lora") or {})}
    tr = {**{
        "epochs": 3,
        "per_device_train_batch_size": 2,
        "gradient_accumulation_steps": 4,
        "learning_rate": 2.0e-4,
        "logging_steps": 10,
        "save_strategy": "epoch",
        "report_to": [],
        "dataset_text_field": "text",
        "max_length": MAX_SEQ_LEN,
        "eos_token": EOS,
    }, **(cfg.get("train") or {})}
    eos = tr["eos_token"]

    parser = argparse.ArgumentParser(description="SemQL 意图 QLoRA SFT")
    parser.add_argument("--dataset", default=cfg.get("dataset", "training_data/sft/train.jsonl"),
                        help="sft_dataset.py 产出的 JSONL")
    parser.add_argument("--base", default=cfg.get("base", DEFAULT_BASE))
    parser.add_argument("--out", default=cfg.get("out", "training_data/sft/adapter"))
    parser.add_argument("--epochs", type=int, default=tr["epochs"])
    args = parser.parse_args(rest)

    try:
        import torch
        from datasets import Dataset
        from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
        from transformers import AutoModelForCausalLM, AutoTokenizer
        from trl import SFTConfig, SFTTrainer
    except ImportError as err:
        sys.exit(f"缺少训练依赖(trl peft bitsandbytes datasets accelerate): {err}")

    tok = AutoTokenizer.from_pretrained(args.base)
    tok.eos_token = eos
    tok.pad_token = tok.eos_token

    # bnb-4bit 仓库自带量化配置,from_pretrained 自动按 4bit 加载
    model = AutoModelForCausalLM.from_pretrained(
        args.base, torch_dtype=torch.bfloat16, device_map={"": 0},
    )
    model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=True)
    model = get_peft_model(model, LoraConfig(
        r=lora["r"], lora_alpha=lora["lora_alpha"],
        lora_dropout=lora["lora_dropout"], task_type=lora["task_type"],
        target_modules=lora["target_modules"],
    ))

    def to_text(ex: dict) -> dict:
        prompt = f"{ex['instruction']}\n\n问句:{ex['input']}\nSemQL:"
        return {"text": f"{prompt} {ex['output']}{eos}"}

    rows = [to_text(ex) for ex in _load_jsonl(args.dataset)]
    trainer = SFTTrainer(
        model=model,
        processing_class=tok,
        train_dataset=Dataset.from_list(rows),
        args=SFTConfig(
            eos_token=eos,
            dataset_text_field=tr["dataset_text_field"],
            max_length=tr["max_length"],
            output_dir=args.out, num_train_epochs=args.epochs,
            per_device_train_batch_size=tr["per_device_train_batch_size"],
            gradient_accumulation_steps=tr["gradient_accumulation_steps"],
            learning_rate=tr["learning_rate"], logging_steps=tr["logging_steps"],
            save_strategy=tr["save_strategy"], report_to=tr["report_to"],
        ),
    )
    trainer.train()
    trainer.save_model(args.out)
    print(f"[SFT] adapter 已保存: {args.out}")
    return 0


def _load_jsonl(path: str) -> list[dict]:
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows


if __name__ == "__main__":
    raise SystemExit(main())
