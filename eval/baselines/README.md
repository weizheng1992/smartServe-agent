# Promptfoo 基线 (Eval Baselines)

本目录存放三套 promptfoo 评测的**钉定基线**,它是"后端 Python 化迁移"(Phase 1 engine-py 重写)的
**等价性验收门禁**:TS 引擎重写为 Python 后,`bun run test:prompt:compare` 必须与基线对齐才允许切流。

## 套件构成

| 基线文件 | 配置 | 覆盖内容 |
|---|---|---|
| `unified.json` | `eval/promptfooconfig.yaml` | 统一 E2E 大盘:意图分类、任务规划、槽位反问、端到端回答质量 |
| `planner.json` | `eval/promptfoo.planner.yaml` | Planner 提示词回归(toolAccuracy scorer) |
| `classify.json` | `eval/promptfoo.classify.yaml` | Classify 提示词回归(intentF1 scorer) |
| `latest.json` | — | 三套摘要的合并索引(不含逐用例明细) |

每个基线文件记录:结果摘要(pass/fail、各 scorer 聚合分)、逐用例通过明细、钉定时间、git SHA、
所用 yaml 的 sha256、promptfoo 版本——任何一项漂移都可追溯。

## 用法

```bash
# 首次钉定基线(任一基线已存在时拒绝执行,防无意漂移)
bun run test:prompt:pin

# 现场重跑三套并与基线对比;任一回归即 exit 1
bun run test:prompt:compare

# 复用已有结果目录(文件名须为 unified.json / planner.json / classify.json,内容为 promptfoo -o 的 JSON 输出)
bun run test:prompt:compare -- --results-dir /path/to/results
```

## 回归判定规则

以下任一情况判为回归,对比失败(exit 1):

- 用例总数、通过数下降,或失败数、错误数上升
- 整体均分或任一 scorer 聚合均分下降
- 基线中通过用例转为失败、或在本次结果中缺失
- 基线中的 scorer 在本次结果中消失

## 何时允许 --update 重新钉定

仅当**有意的提示词/引擎行为变更**经过评审接受后,在该行为变更的同一个 PR 中执行
`bun run test:prompt:pin -- --update` 并提交新基线。禁止为了"让对比通过"而静默重钉。
