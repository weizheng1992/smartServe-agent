# PAI-DSW QLoRA SFT 训练记录（2026-09-20 夜）

> **一句话结论**：训练任务在阿里云免费试用算力上完整运行并通过闲置关机自动停机；LoRA adapter 产物在实例 `/mnt/workspace/adapter/`，**15 天内务必取回**（停止超 15 天免费云盘清空）。
> **配套指南**：部署（vLLM/Ollama/EAS/engine 接入）与测评（mapping.json 字段准确率 + promptfoo 门）见 [sft-deploy-eval.md](sft-deploy-eval.md)。

## 结论速览

| 项 | 状态 |
|---|---|
| 训练任务 | 按预期时间窗结束（最后人工观测 46-50% 健康推进 → 00:02 起 GPU 全 0%） |
| 最终确认 | ✅ **已确认完成**：`adapter_model.safetensors` 落盘时间 09-20 23:49（`trainer.save_model` 仅在 1680 步全部跑完后执行），早于预估 40 分钟 |
| 取回状态 | ✅ adapter 已取回：`~/Downloads/adapter_final.zip`（146MB，完整性校验通过），并解压至仓库 `services/engine-py/training_data/sft/adapter/`；实例随后停机 |
| 实例状态 | **Stopped**（闲置自动关机策略生效：CPU<5% 且 GPU<10% 持续 30 分钟），无需人工停机 |
| 计算时消耗 | 估算全晚合计 **~45 计算时**（9 月额度 250 的 ~18%），明细见下 |
| 产物 | `/mnt/workspace/adapter/`（LoRA 权重，几十 MB）+ `adapter/checkpoint-*/`（epoch 中途检查点） |

## 一、部署信息

- **账号**：1408322600972032（aliyun CLI OAuth，default profile，默认 region cn-beijing）
- **实例**：`dsw-uh6r6vu6jojv3396lg`（名 `qwen`），PAI 工作空间 cn-beijing `453901`
- **规格**：`ecs.gn7i-c8g1.2xlarge`（NVIDIA A10 24GB / 8 vCPU / 30GiB）
- **镜像**：`modelscope:1.31.0-pytorch2.8.0-gpu-py311-cu124`（自带 vLLM 0.11，自测环节免装）
- **计费**：DSW 免费试用资源包（每月 250 计算时 × 3 个月，至 2026-12-18）；A10 档 **6.991 计算时/小时**

**计算时账（估算）**：ROCm 废弃实例运行约 45 分钟 ≈ 5；正式实例 19:00~00:35 约 5.5-6h ≈ 38-42；合计 ≈ 45（含当晚所有失败尝试的加载期）。

## 二、排障记录（三个坑，按遭遇顺序）

1. **torchao 与镜像 torch 2.8 不兼容**：`pip install unsloth trl ...` 拉进最新 torchao（要 torch≥2.11），经 transformers quantizers 导入链炸出 `cannot import name 'ScalingType'`。修法：`pip uninstall -y torchao`（QLoRA bitsandbytes 路径不需要它；**不要升 torch**，会破坏 unsloth/xformers 二进制配对）。
2. **trl 0.2x API 变更**：`SFTTrainer(tokenizer=...)` → `processing_class=`；`dataset_text_field` / `max_seq_length` 移入 `SFTConfig`（长度参数新名 `max_length`）。
3. **unsloth 补丁层注入坏 eos（终极坑）**：unsloth 运行时把 eos 偷换成词表外占位符 `'<EOS_TOKEN>'`，trl 的 `args.eos_token` 词表校验必挂；显式传 `SFTConfig(eos_token="<|im_end|>")`、时序压制赋值**均被覆写**（三连败，trl 源码 666 行确证它读的就是被偷换后的值）。**终局：弃用 unsloth，整文件重写为标准栈** transformers + peft + trl（无补丁层即无注入者），EOS 写字面量 `<|im_end|>`。代价：无 unsloth 加速，时长 +50%，免费额度内可忽略。
   - 另有下载坑备查：xet 通道会真卡死（`du` 半小时不动），修法 `HF_HUB_DISABLE_XET=1` + `unset HF_ENDPOINT` 重跑续传；hf-mirror 云内超时，ModelScope 内网加速才是快路径（峰值 ~150MB/s）。

**教训**：远程实例上"修—跑—看"循环每轮约 5 分钟且靠人肉中转，同因连续失败 3 次就该换栈/换战场，不要打第 4 个补丁。

## 三、训练配置

| 项 | 值 |
|---|---|
| 任务 | 问句 + 指标闭集 → SemQL JSON（模型只学语义理解，不写 SQL，铁律 08-D1） |
| 基座 | `unsloth/Qwen2.5-7B-Instruct-bnb-4bit`（本地 modelscope 缓存目录加载，零下载） |
| 数据 | `train.jsonl` **4478 样本**（注：本地 sft_dataset.py 生成的是 875 条，云端实跑文件为 4478 条，来源待查但不影响本次训练） |
| LoRA | r=16, alpha=32, dropout=0.05, target: q/k/v/o + gate/up/down_proj |
| 量化 | nf4 4bit（仓库自带 bnb 量化配置），bf16 计算 |
| 批次 | batch 2 × grad_accum 4（有效 8），max_length 2048 |
| 优化 | lr 2e-4, 3 epochs, 共 **1680 步**, eos=`<|im_end|>` |

**过程观测**（人工最后观测点 46-50%）：mean_token_accuracy 72% → **99.6%** 并稳定；loss 1.38 → 0.05（前 10 个日志点内，闭集格式任务收敛极快）→ ~0.012 平台缓降；9.28s/步无衰减。

## 四、产物取回（重要：15 天窗口）

1. 控制台启动实例 `qwen`（或告诉我来启）→ 打开 JupyterLab
2. Terminal 先确认：`tail -5 train.log`（应见 `[SFT] adapter 已保存: adapter`；顺带把最终 loss/train_runtime 记到本文档）
3. 打包：`zip -r adapter.zip adapter`
4. 文件浏览器右键 `adapter.zip` → Download 存回 Mac
5. **立即停止实例**（或喊我停）

## 五、下一步

1. **vLLM 自测**（镜像自带 vLLM 0.11）：
   ```bash
   vllm serve <基座> --enable-lora --lora-modules semql=./adapter --port 8000
   # curl /v1/chat/completions model=semql,喂几条问句看 SemQL JSON 是否规整
   ```
2. **接回 engine**：按 `services/engine-py/scripts/training/README.md` 五步——影子跑（只记日志）→ promptfoo intentF1 达标 → `AI_BASE_URL`/`AI_MODEL` 配置切换（接缝 `engine_py/llm/chat.py`）；回滚 = 改回一行 env。
3. 生产部署选项：PAI-EAS（单独计费）或 merge 后转 GGUF 本地 Ollama，按 QPS/预算定。

## 六、本机同步变更

- `services/engine-py/scripts/training/sft_train.py`：已重写为标准栈（与云端执行版一致，待 commit）
- `services/engine-py/training_data/sft/train.jsonl`：本地生成版（875 条；云端实跑为 4478 条版，差异待查）
- 定时任务 `automation-9556080f`（本次自动检查/写档）为一次性，已执行完毕，无残留
