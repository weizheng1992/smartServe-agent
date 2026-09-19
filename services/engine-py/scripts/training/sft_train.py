"""QLoRA SFT 训练(用户文档路线:QLoRA SFT → 可选 DPO;Unsloth 单卡首选)。

任务:问句 + 指标闭集目录 → SemQL JSON(模型只学语义理解,永不写 SQL,
铁律 08-D1)。数据由 sft_dataset.py 构建(评测集纯门永不入训)。

用法(services/engine-py 下)::

    uv run python scripts/training/sft_train.py \\
        --dataset training_data/sft/train.jsonl \\
        --base unsloth/Qwen2.5-7B-Instruct-bnb-4bit \\
        --out training_data/sft/adapter

依赖(文档栈)::

    uv pip install unsloth trl peft bitsandbytes datasets
    (未安装时报错退出,不影响 CI——训练按需在 GPU 环境执行)
"""

from __future__ import annotations

import argparse
import sys

DEFAULT_BASE = "unsloth/Qwen2.5-7B-Instruct-bnb-4bit"
MAX_SEQ_LEN = 2048


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SemQL 意图 QLoRA SFT")
    parser.add_argument("--dataset", required=True, help="sft_dataset.py 产出的 JSONL")
    parser.add_argument("--base", default=DEFAULT_BASE)
    parser.add_argument("--out", default="training_data/sft/adapter")
    parser.add_argument("--epochs", type=int, default=3)
    args = parser.parse_args(argv)

    try:
        from unsloth import FastLanguageModel
        from trl import SFTConfig, SFTTrainer
    except ImportError as err:
        sys.exit(f"缺少训练依赖(按文档 pip install unsloth trl peft bitsandbytes): {err}")

    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=args.base, max_seq_length=MAX_SEQ_LEN, load_in_4bit=True,
    )
    model = FastLanguageModel.get_peft_model(
        model,
        r=16, lora_alpha=32, lora_dropout=0.05,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
        use_gradient_checkpointing="unsloth",
    )

    def to_text(ex: dict) -> dict:
        prompt = f"{ex['instruction']}\n\n问句:{ex['input']}\nSemQL:"
        return {"text": f"{prompt} {ex['output']}{tokenizer.eos_token}"}

    dataset = [to_text(ex) for ex in _load_jsonl(args.dataset)]
    trainer = SFTTrainer(
        model=model,
        tokenizer=tokenizer,
        train_dataset=dataset,
        dataset_text_field="text",
        max_seq_length=MAX_SEQ_LEN,
        args={"output_dir": args.out, "num_train_epochs": args.epochs,
              "per_device_train_batch_size": 2, "gradient_accumulation_steps": 4,
              "learning_rate": 2e-4, "logging_steps": 10, "save_strategy": "epoch"},
    )
    trainer.train()
    trainer.save_model(args.out)
    print(f"[SFT] adapter 已保存: {args.out}")
    return 0


def _load_jsonl(path: str) -> list[dict]:
    import json

    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows


if __name__ == "__main__":
    raise SystemExit(main())
