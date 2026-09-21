"""QLoRA SFT 训练(标准栈:transformers + peft + trl)。

任务:问句 + 指标闭集目录 → SemQL JSON(模型只学语义理解,永不写 SQL,
铁律 08-D1)。数据由 sft_dataset.py 构建(评测集纯门永不入训)。

不用 unsloth:其加载层会向 trainer 注入词表外 eos 占位符('<EOS_TOKEN>'),
trl 校验必挂;标准栈时长约多一半,在免费计算时额度内可忽略。

用法(services/engine-py 下)::

    uv run python scripts/training/sft_train.py \\
        --dataset training_data/sft/train.jsonl \\
        --base unsloth/Qwen2.5-7B-Instruct-bnb-4bit \\
        --out training_data/sft/adapter

依赖::

    uv pip install trl peft bitsandbytes datasets accelerate
"""

from __future__ import annotations

import argparse
import json
import sys

DEFAULT_BASE = "Qwen/Qwen2.5-7B-Instruct"
MAX_SEQ_LEN = 2048
EOS = "<|im_end|>"  # Qwen2.5-Instruct 真实结束符;写字面量,不读 tokenizer 运行时值


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SemQL 意图 QLoRA SFT")
    parser.add_argument("--dataset", required=True, help="sft_dataset.py 产出的 JSONL")
    parser.add_argument("--base", default=DEFAULT_BASE)
    parser.add_argument("--out", default="training_data/sft/adapter")
    parser.add_argument("--epochs", type=int, default=3)
    args = parser.parse_args(argv)

    try:
        import torch
        from datasets import Dataset
        from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
        from transformers import AutoModelForCausalLM, AutoTokenizer
        from trl import SFTConfig, SFTTrainer
    except ImportError as err:
        sys.exit(f"缺少训练依赖(trl peft bitsandbytes datasets accelerate): {err}")

    tok = AutoTokenizer.from_pretrained(args.base)
    tok.eos_token = EOS
    tok.pad_token = tok.eos_token

    # bnb-4bit 仓库自带量化配置,from_pretrained 自动按 4bit 加载
    model = AutoModelForCausalLM.from_pretrained(
        args.base, torch_dtype=torch.bfloat16, device_map={"": 0},
    )
    model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=True)
    model = get_peft_model(model, LoraConfig(
        r=16, lora_alpha=32, lora_dropout=0.05, task_type="CAUSAL_LM",
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                        "gate_proj", "up_proj", "down_proj"],
    ))

    def to_text(ex: dict) -> dict:
        prompt = f"{ex['instruction']}\n\n问句:{ex['input']}\nSemQL:"
        return {"text": f"{prompt} {ex['output']}{EOS}"}

    rows = [to_text(ex) for ex in _load_jsonl(args.dataset)]
    trainer = SFTTrainer(
        model=model,
        processing_class=tok,
        train_dataset=Dataset.from_list(rows),
        args=SFTConfig(
            eos_token=EOS,
            dataset_text_field="text",
            max_length=MAX_SEQ_LEN,
            output_dir=args.out, num_train_epochs=args.epochs,
            per_device_train_batch_size=2, gradient_accumulation_steps=4,
            learning_rate=2e-4, logging_steps=10, save_strategy="epoch",
            report_to=[],
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
