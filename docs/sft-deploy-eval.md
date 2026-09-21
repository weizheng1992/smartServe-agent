# SFT 模型部署与测评指南（SemQL 意图解析）

配套：训练记录见 [pai-dsw-sft-run-20260920.md](pai-dsw-sft-run-20260920.md)，训练脚本 `services/engine-py/scripts/training/sft_train.py`（标准 transformers+peft+trl 栈）。

## 一、文件放置与 GitHub 策略

| 文件 | 位置 | 是否入库 |
|---|---|---|
| 训练脚本 | `services/engine-py/scripts/training/sft_train.py` | ✅ 入库 |
| 训练记录（本文档姊妹篇） | `docs/pai-dsw-sft-run-20260920.md` | ✅ 入库 |
| 本指南 | `docs/sft-deploy-eval.md` | ✅ 入库 |
| **LoRA 权重** `adapter_model.safetensors`（154MB） | `services/engine-py/training_data/sft/adapter/` | ❌ **gitignore** |

**权重不入库的原因**：GitHub 单文件硬上限 100MB，154MB 直接 push 被拒；权重备份现存两处——`~/Downloads/adapter_final.zip`（146MB）和云端实例 `/mnt/workspace/adapter/`（实例停止超 15 天云盘清空，故 zip 是主备份）。若将来需要多人共享权重再上 git-lfs（免费额度 1GB 存储/带宽，超量计费）。

## 二、部署

### 2.1 云端 vLLM 自测（一次性验证，推荐先做）

DSW 实例已装 vLLM 0.11。实例 Terminal：

```bash
cd /mnt/workspace
# 基座建议先手动经 ModelScope 内网拉全精度版(vLLM 无 ModelScope 兜底,直连 hf-mirror 易卡):
modelscope download --model Qwen/Qwen2.5-7B-Instruct \
  --local_dir /mnt/workspace/base_models/Qwen2.5-7B-Instruct
# 用本地目录起服务(LoRA 与量化基座/全精度基座通用):
vllm serve /mnt/workspace/base_models/Qwen2.5-7B-Instruct \
  --enable-lora --lora-modules semql=./adapter --port 8000 &
```

**冒烟必须用真实 instruction**（训练时的指标闭集指令，存在 `train.jsonl` 首行的 `instruction` 字段；直接 curl 字面量会让模型按字面回答——实测教训，见下）：

```bash
cat > smoke_semql.py <<'PYEOF'
import json, urllib.request
instr = json.loads(open('/mnt/workspace/train.jsonl').readline())['instruction']
def ask(q):
    body = json.dumps({"model":"semql","messages":[
        {"role":"user","content":f"{instr}\n\n问句:{q}"}]}).encode()
    req = urllib.request.Request("http://127.0.0.1:8000/v1/chat/completions",
                                 body, {"Content-Type":"application/json"})
    return json.load(urllib.request.urlopen(req))["choices"][0]["message"]["content"]
for q in ["近30天背包收纳销量前10", "卖得最差的商品", "上个月gmv最高的品类"]:
    print("问:", q); print("答:", ask(q)[:400]); print("-"*60)
PYEOF
python3 smoke_semql.py
```

每问应输出一行规整 SemQL JSON（metric/direction/limit/time_window/category 全在闭集内）。**验证完 `pkill -f vllm` 并停机**。

> **2026-09-21 实测记录**：`vllm serve /mnt/workspace/base_models/Qwen2.5-7B-Instruct --enable-lora --lora-modules semql=./adapter` 起服务成功，`model=semql` 正常路由（LoRA 挂载 ✓）。首次冒烟误把字面量 `<train.jsonl 的 instruction>` 当提示词（prompt_tokens 仅 49，正常应 500+），模型按字面回答"如何分析 train.jsonl"——属测试输入错误而非模型问题；换真实 instruction 后的三问结果见本文档末尾"自测结果"。

### 2.2 本地 Mac 零成本（日常开发用）

```bash
# 1) 合并 adapter 进基座(在能跑 torch 的环境,如 DSW 或云端)
#    peft: model.merge_and_unload(); save_pretrained("merged/")
# 2) 转 GGUF Q4(llama.cpp convert_hf_to_gguf.py + quantize)
# 3) Mac 上 Ollama 运行(7B Q4 ≈ 4.5GB 内存)
ollama create semql -f Modelfile   # FROM merged-q4.gguf + 模板指向 <|im_end|>
```

### 2.3 生产 PAI-EAS（对外服务才需要）

控制台 → 模型在线服务（EAS）→ 部署 LLM 场景（vLLM）+ LoRA 挂 OSS。⚠️ **EAS 单独计费，不在 DSW 试用包内**；用完释放。adapter 传 OSS 可由 CLI/ossutil 代办。

### 2.4 接回 engine（README 五步浓缩）

1. 产物入位：`adapter/` 放服务可访问路径
2. 影子跑：新端点并行打分、只记日志不生效，跑 1-2 周
3. 达标判定：promptfoo intentF1 同评测集 ≥ 现有基线
4. 切换：`AI_BASE_URL`/`AI_MODEL` 指向新端点（接缝 `engine_py/llm/chat.py`）
5. 回滚 = 环境变量改回一行

## 三、测评

### 3.1 评测集

`eval/testCases/data_analytics/mapping.json`：**42 条** promptfoo 用例（input + expectedMetric/Direction/TimeWindow），即训练时的纯门——**已排除在 4478 条训练集之外**，可直接用于泛化检验。

### 3.2 快速字段准确率（起好 2.1 端点后跑）

```python
# eval_sft_quick.py — 对 mapping.json 逐条打分,输出字段级准确率
import json, re, argparse, urllib.request

ap = argparse.ArgumentParser()
ap.add_argument('--base-url', default='http://127.0.0.1:8000/v1')
ap.add_argument('--model', default='semql')
ap.add_argument('--train-jsonl', default='../services/engine-py/training_data/sft/train.jsonl')
ap.add_argument('--cases', default='eval/testCases/data_analytics/mapping.json')
a = ap.parse_args()

instr = json.loads(open(a.train_jsonl).readline())['instruction']  # 与训练完全一致的指令模板
cases = json.load(open(a.cases))

def ask(q):
    body = json.dumps({"model": a.model, "messages": [
        {"role": "user", "content": f"{instr}\n\n问句:{q}"}]}).encode()
    req = urllib.request.Request(a.base_url + "/chat/completions", body,
                                 {"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req))["choices"][0]["message"]["content"]

def semql(text):
    m = re.search(r'\{.*\}', text, re.S)          # 容忍 markdown 包裹
    return json.loads(m.group()) if m else {}

stat = {"metric": 0, "direction": 0, "time_window": 0, "total": 0}
for c in cases:
    v = c["vars"]
    out = semql(ask(v["input"]))
    stat["total"] += 1
    stat["metric"]      += out.get("metric") == v.get("expectedMetric")
    stat["direction"]   += out.get("direction") == v.get("expectedDirection")
    ew, ow = v.get("expectedTimeWindow"), out.get("time_window")
    stat["time_window"] += (ew is None and ow is None) or \
                           (ew and ow and ew.get("kind") == ow.get("kind"))
t = stat["total"]
print(f"n={t}  metric {stat['metric']/t:.1%}  direction {stat['direction']/t:.1%}  time_window {stat['time_window']/t:.1%}")
```

**基线对比**：把 `--base-url/--model` 指向现有 engine 的 LLM 端点再跑一遍，两份字段准确率并排看——这就是影子跑的浓缩版。达标线按 README 口径：**intentF1（此处为字段准确率）≥ 现有基线**。

### 3.3 正式门（promptfoo）

`mapping.json` 本身就是 promptfoo 用例（scorer `scorers/data_mapping.py:get_assert`）。SFT 端点接入 promptfoo 时 provider 指向 `http://127.0.0.1:8000/v1`（model=semql）；若 scorer 期望的是 engine 包装格式而非裸 SemQL，加一层薄 provider 后处理（从 content 提取 JSON 再按原格式包一层），**不要改评测集本身**。

### 3.4 判读纪律

- 42 条小样本，字段准确率差 ±2% 以内算噪声，多跑两次取稳定值
- 训练集 4478 条里合成组合占大头，mapping.json 是真实问法——**真实问法上的表现权重高于训练指标**（训练 token 准确率 99.6% 只说明格式学会了）
- 评测集永远不入训（sft_dataset.py 的排除逻辑是护栏），新增评测用例先过一遍排除校验

## 四、自测结果（2026-09-21，DSW vLLM 0.11 + semql LoRA，真实 instruction）

| 问句 | 模型输出 |
|---|---|
| 近30天背包收纳销量前10 | `{"metric": "volume", "direction": "DESC", "limit": 10, "time_window": {"kind": "last_30d"}, "category": "背包收纳"}` |
| 卖得最差的商品 | `{"metric": "volume", "direction": "ASC", "limit": 5, "time_window": null, "category": null}` |
| 上个月gmv最高的品类 | `{"metric": "gmv", "direction": "DESC", "limit": 5, "time_window": {"kind": "last_month"}, "category": null}` |

**判读**：

- 三问五槽全对：同义词"销量"→volume；**"最差"→ASC 方向翻转命中**（08-P1 回归门用例）；三种时间窗 kind 各就各位；limit 默认 5、显式"前10"→10；品类过滤正确识别"背包收纳"
- 第 3 问 `category=null` 是**正确行为**："品类"在句中是聚合维度而非过滤条件，SemQL 没有 group-by 槽位，模型没有过度填槽
- 输出带 `SemQL: ` 前缀（训练文本格式的自然产物），下游解析用 `\{.*\}` 正则提取 JSON 即可（3.2 脚本已容错）
- 对照首测教训：无 instruction 时通用基座输出整页分析代码；挂 adapter + 真实 instruction 后输出严格受限的 SemQL——**LoRA 生效的直接证据**

**遗留**：42 条 mapping.json 字段准确率脚本尚未实跑（需端点持续在线），下次开实例时补；跑完与现有基线并排对比即为接入决策依据。
