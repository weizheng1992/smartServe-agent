# 训练脚手架（scripts/training/）

11 号票「训练方案模板」的代码化：**现在不训练**，但流水线全部就位——数据到门槛后，
改一份 TOML 配置即可完成 预标 → 加工 → 训练 → 评测 → 产出可接入的模型目录。

## 位置与依赖

- 零新增依赖：torch / sentence-transformers 是 engine 既有依赖，配置读取用 py312 标准库 tomllib。
- 所有命令在 `services/engine-py/` 下以 `uv run` 执行；配置里的相对路径按此 CWD 解析。

## 流水线（对应 11-D3 六步）

```
export_intent_data.py        # ① 水龙头导出(已落码,数据自 2026-09-17 自动积累)
        │
prelabel.py                  # ② LLM 第二意见;管线 intent 是第一意见
        │                      分歧/低置信 → need_review=true,人工只裁这部分
        ▼
(人工复核 need_review)        # ③ 编辑器/表格改 label,清掉 review 标记
        │
prepare_data.py              # ④ 去重 → 评测句近邻过滤(cos≥0.90 防泄漏) → 分层切分
        │
train.py                     # ⑤ embedding + torch 线性头(CPU 分钟级);产出 run 目录
        │
evaluate.py                  # ⑥ heldout 复检 / 新数据复检,出 markdown 报告
```

## 快速开始（冒烟，不下载模型、不需要数据）

```bash
# 把 example 复制为正式配置,encoder 先用 hash 冒烟
cp scripts/training/configs/metric_head.example.toml /tmp/smoke.toml
sed -i '' 's|BAAI/bge-small-zh-v1.5|hash|' /tmp/smoke.toml   # macOS;Linux 用 sed -i
uv run python scripts/training/prepare_data.py --config /tmp/smoke.toml
uv run python scripts/training/train.py --config /tmp/smoke.toml
uv run python scripts/training/evaluate.py --run-dir training_runs/metric_head \
    --data training_data/metric_head/processed/heldout.jsonl
```

真跑只改两处：`encoder = "BAAI/bge-small-zh-v1.5"`，`train_jsonl` 指向标注数据。

## 什么时候可以训（11-D2 触发条件）

| 头 | 门槛 | 现状（06 号实测口径） |
|---|---|---|
| 指标映射头 | 150–400 句，随时可启动 | 有机速率 5–10 唯一句/天，数天–2 周攒够 |
| 意图分类头 | 唯一句 ≥500 且每意图 ≥32（合成 ≤50%） | 被动 1–2 个月；急用则 LLM 扩写造数 |

每月跑一次导出统计；连续两月唯一句增速 <300/月 → 转主动造数；
intent_conflict 唯一句/周连升两周 = 漂移重训信号。**先清 71 条 badcase 冲突队列。**

## 产物与三缝接入

`run_dir/` 内四件：`head.pt`（线性头权重）、`labels.json`（闭集标签序 + encoder 名）、
`config.snapshot.toml`（训练配置快照）、`metrics.json`（每类 P/R/F1）。

- 缝②指标映射：`MetricQueryEngine.resolve` 前端 adapter 加载 run 目录，L0 未命中处调用；
- 缝①意图分类：`IntentScorer` 新 adapter + `get_intent_classifier()` 配置切换；
- 接入纪律：先影子跑（并行打分记日志对比）→ promptfoo intentF1 同评测集达标且高于基线
  → 配置切换；**回滚 = 配置回退一行**。评测集永远不入训（prepare 的近邻过滤就是护栏）。

## 文件清单

| 文件 | 职责 |
|---|---|
| `common.py` | 配置/JSONL 读写、编码器工厂（hash 冒烟 / sentence-transformers）、指标 |
| `prelabel.py` | LLM 预标（httpx 直连 OpenAI 兼容端点，env 取 AI_BASE_URL/AI_MODEL） |
| `prepare_data.py` | 去重 / 近邻过滤 / 分层切分 / 标签闭集校验，出 stats.json（够不够训看它） |
| `train.py` | config 驱动训练，产出 run 目录 |
| `evaluate.py` | 对任意 JSONL 复检 run，出 markdown 报告 |
| `configs/*.example.toml` | 两份配置样例（指标头 / 意图头），复制后修改即用 |
| `tests/test_training_pipeline.py` | 端到端测试（hash 编码器，不下载模型不依赖 DB） |

决策溯源：wayfinder 票 05（落点）/ 06（数据可行性）/ 07（水龙头）/ 11（决策文档），
见 `docs/wayfinder/mall-data-agent-split/issues/`。

## 部署与接入（训练完 → 上线五步）

**形态：进程内部署，无独立模型服务**（05/11 号决议）。产物 = 不改动的预训练 bge
编码器（~100MB，与线上判重缓存同一个进程内实例，零额外内存）+ 你训练的一层
线性头（head.pt，几 KB）。推理 = 句向量 × 矩阵，CPU 单句毫秒级。

1. 产物入位：`training_runs/<name>/` 拷到 `models/<name>/`（head.pt + labels.json；
   encoder 走本地 HF 缓存或随包分发，100MB 级适合进发布产物/git-lfs）；
2. 影子跑：adapter 注册为「并行打分、只记日志不生效」，跑 1-2 周对比基线；
3. 达标判定：promptfoo intentF1 同评测集 ≥ 现有基线（evaluate.py 报告为证）；
4. 切换生效：配置切换（IntentScorer / resolve 前端换 adapter 指向 models/<name>）；
5. 回滚：配置回退一行，无需回滚代码。

升级路径：缝③换模位支持换微调后的 bge 权重（仍是进程内）；若将来 QPS 需要
独立推理服务，演化方向为 TEI（Text Embeddings Inference），当前量级不需要。
