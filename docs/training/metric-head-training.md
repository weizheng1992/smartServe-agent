# 指标映射分类头训练文档（完整版）

> 训练日期 2026-09-18 · 产物 `services/engine-py/training_runs/metric_head/` · 本文记录从数据源到部署的完整事实链，所有数字为真实运行结果。

---

## 1. 这个模型是什么

一个**意图归一分类器**：输入商户口语问句（如「卖得最差的商品」「差评最多的 SKU」），输出 12 类闭集标签之一 + 置信度。它是 data agent 口语理解链路（L0 词表 → 分类头 → LLM 兜底）中间的**确定性加速层**——L0 词表没接住的口语由它归类，接不住的再放行 LLM 兜底。

- 底座：`BAAI/bge-small-zh-v1.5`（约 100MB / 2400 万参数的中文语义向量模型，**冻结不训练**）
- 可训练部分：一个 `torch.nn.Linear(384 → 12)` 单层分类头（**约 4.6K 参数 / 26KB 文件**）
- 任务形态：SetFit 式少样本文本分类（句子嵌入 + 线性分类），非生成式、非 LLM 微调

---

## 2. 数据源从哪来

### 2.1 种子数据（本次训练实际使用）：词表自动弱标注

生成器：`scripts/training/seed_from_registry.py`
原理：指标注册表（`metric_registry.py`，单一事实源）里每个指标自带同义词/标签/示例问句，逐条展开为带标签训练句：

```
「有什么优惠活动」→ promotion_query
「卖得好」→ gmv
「压货」→ stock_risk
```

外加三类变体模板（「帮我看看X」「X的商品排行」「查一下X」）和**反向词变体**（「销售额最低」→ 同标签，方向语义由推理侧另行处理）。

**实际产出：590 句 × 11 类**（`unsupported` 兜底类由配置声明、种子不造），每类 29–79 句：

| 类别 | 句数 | 类别 | 句数 | 类别 | 句数 |
|---|---|---|---|---|---|
| gmv | 71 | gross_profit | 71 | stock_risk | 71 |
| volume | 79 | margin_rate | 54 | review_bad | 46 |
| session_volume | 53 | gmv_trend | 50 | after_sale_overview | 37 |
| refund_rate | 29 | ai_resolution_rate | 29 | | |

### 2.2 持续供给（生产流量，水龙头自动积累）

- 采集 CLI：`scripts/export_intent_data.py --source intent|low_confidence|badcase`（JSONL，同格式）
- 来源表：engine 库 `intent_logs`（每次意图判定落一行）/ `low_confidence_logs`（低置信子集）/ `badcase_candidates`（冲突信号，含 thread_id 可回联原文）
- 实测积累：intent_logs 1966 行（约两周）、badcase 547 行；去重后唯一句增速约 5–10/天
- `intent_logs` 表本身无 TTL，数据持续保留

### 2.3 评测隔离（blocklist）

`eval/testCases/data_analytics/mapping.json`（promptfoo 用例，8 句）作为**评测冻结门**：训练前做近邻过滤，与评测句余弦 ≥ 0.90 的训练句剔除（本次实际剔除 4 句），保证评测集永不入训。

---

## 3. 数据格式与加工

### 3.1 格式：JSONL，每行一条

```json
{"query": "帮我看看卖得好", "label": "gmv", "source": "registry_seed"}
```

- `query`：问句原文（字段名可经配置 `input_field` 调整）
- `label`：闭集标签（必须 ∈ 配置 `labels` 列表，越界直接报错拒绝）

### 3.2 加工流水线（`prepare_data.py`，一条命令完成）

```
590 句种子
  → 按句去重（精确匹配，本次剔 0 —— 种子本身无重复）
  → 评测句近邻过滤（bge 余弦 ≥ 0.90 剔除，本次剔 4 句 —— 挡评测泄漏）
  → 分层切分（每类按比例抽 heldout，seed=42 可复现）
  → train.jsonl 497 句 / heldout.jsonl 89 句 + stats.json（各类样本数报表）
```

`stats.json` 直接回答「够不够训」：每类样本数、<32 句的类别自动提示（本次 refund_rate / ai_resolution_rate / unsupported 三类 29 句略低，SetFit 8 句/类门槛已远超）。

---

## 4. 训练：库、参数、过程

### 4.1 库（全部为 engine 既有依赖，零新增）

| 环节 | 库 | 用途 |
|---|---|---|
| 编码 | `sentence-transformers` | 加载 bge，590 句 → 384 维向量矩阵（一次前向）|
| 分类头 | `torch.nn.Linear` | 唯一可训练层 |
| 损失 | `torch.nn.CrossEntropyLoss` | 12 类闭集交叉熵 |
| 优化器 | `torch.optim.Adam` | lr=0.01 |
| 配置 | py312 标准库 `tomllib` | TOML 配置读取 |

### 4.2 参数（`configs/metric_head.toml`，实际生效值）

```toml
[model]
encoder = "BAAI/bge-small-zh-v1.5"   # 冻结,不参与梯度
device  = "cpu"                       # 无 GPU 需求

[train]
epochs = 20          # 实测第 6 epoch 已收敛到 98.9%,20 为余量
batch_size = 32
lr = 0.01            # Adam
seed = 42            # 全程可复现

[data]
heldout_ratio = 0.15 # 实际切出 89 句(分层)
```

### 4.3 训练过程（真实曲线，`metrics.json` → `curve.html` 可视化）

| epoch | train_loss | heldout 准确率 |
|---|---|---|
| 1 | 2.1402 | 67.4% |
| 2 | 1.5312 | 84.3% |
| 3 | 1.1185 | 95.5% |
| 6 | — | **98.88%（收敛）** |
| 20 | **0.1095** | 98.88% |

- 损失从 ln(12)≈2.48 的随机水平降至 **0.11**（下降 95%），无过拟合回升
- 训练全程 **CPU 约 2 分钟**（含 bge 前向；线性头本身秒级）
- 曲线图：`training_runs/metric_head/curve.html`（浏览器直接打开）

---

## 5. 训练结果（heldout 89 句，从未参与训练）

| 指标 | 值 |
|---|---|
| **accuracy** | **98.88%** |
| **macro F1** | **0.9074** |

逐类（support = heldout 句数）：11 类 F1 全部 ≥ 0.94（volume/gross_profit/margin_rate/stock_risk/review_bad/refund_rate/after_sale_overview/session_volume/ai_resolution_rate 均 1.0；gmv 0.95、gmv_trend 0.94；unsupported 兜底类 heldout 无样本故无分）。训练集 accuracy 100% —— 线性头对 bge 向量完全可分。

---

## 6. 产物与部署

### 6.1 产物四件（`training_runs/metric_head/`）

| 文件 | 大小 | 内容 |
|---|---|---|
| `head.pt` | 26KB | 线性头权重（唯一的「模型」）|
| `labels.json` | <1KB | 闭集标签序 + encoder 名（推理 argmax 索引即此序）|
| `config.snapshot.toml` | 1.5KB | 训练配置快照（评测/接入据此加载同款 encoder）|
| `metrics.json` | 5KB | 逐 epoch 损失/准确率曲线 + 最终指标 |

### 6.2 部署形态：**进程内，无独立模型服务**

推理 = 句向量 × 线性头矩阵，CPU 单句毫秒级。bge 编码器与线上判重缓存**共享同一进程内实例**（网关启动时已加载），接入后额外内存 ≈ 几 KB 权重。`head.pt` 走 git 版本管理。

### 6.3 三态接入（环境变量控制，回滚 = 删变量）

```bash
AI_METRIC_HEAD=shadow   # 影子跑:并行打分只记日志,判定不变(1-2 周对比期)
AI_METRIC_HEAD=on       # 接管:L0 词表未命中处由分类头回答(置信 ≥0.5,低置信放行 LLM 兜底)
# 回滚 = 移除 AI_METRIC_HEAD,不改编排一行
```

- 代码：`engine_py/analytics/metric_head.py`（加载器）+ `engine.py` resolve 三态接线
- 编码器加载本地缓存优先（`local_files_only` + hf-mirror 兜底），线上 HF 不可达不挂起
- 权限闸不绕过：分类头结果仍过角色闭集过滤（契约测试覆盖）

### 6.4 接入纪律（11-D4）

影子跑 1–2 周 → 日志分歧率达标 → 配置切 on → 异常移除变量即回滚。分歧案例即下一轮训练数据。

---

## 7. 复现步骤（三条命令）

```bash
cd services/engine-py
uv run python scripts/training/seed_from_registry.py --out training_data/metric_head/seed.jsonl
uv run python scripts/training/prepare_data.py --config scripts/training/configs/metric_head.toml
uv run python scripts/training/train.py      --config scripts/training/configs/metric_head.toml
# 评测: uv run python scripts/training/evaluate.py --run-dir training_runs/metric_head \
#         --data training_data/metric_head/processed/heldout.jsonl
```

冒烟（不下载模型）：配置 `encoder = "hash"` 即可用确定性哈希编码器走全流程（CI 测试即此形态，6 用例秒级）。

---

## 8. 已知边界与后续

- 种子为词面模板弱标注，heldout 98.9% 偏乐观（同分布）；真实野口语的检验靠**影子跑**，分歧案例经水龙头回流再训练
- refund_rate / ai_resolution_rate / unsupported 三类 29 句，低于 32 句稳定线 —— 随水龙头补足后重训
- 漂移重训信号：intent_conflict 唯一句/周连续两周上升（11-D2）
- 环境注意：训练/推理需 `HF_HUB_OFFLINE=1`（模型已在本地缓存；在线镜像可能挂起）
