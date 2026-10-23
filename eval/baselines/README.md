# Promptfoo 基线 (Eval Baselines)

本目录存放 promptfoo 评测的**钉定基线**,它是"后端 Python 化迁移"(Phase 1 engine-py 重写)的
**等价性验收门禁**:TS 引擎重写为 Python 后,`bun run test:prompt:compare` 必须与基线对齐才允许切流。

## 套件构成(六册,2026-10-23 data/t1t2 入列)

| 基线文件 | 配置 | 覆盖内容 |
|---|---|---|
| `unified.json` | `eval/promptfooconfig.yaml` | 统一 E2E 大盘:意图分类(生产瀑布真跑)、任务规划、槽位反问、端到端回答质量、咨询直答快轨、事故回归、多租户品牌隔离、安全注入、RAG 忠实度(55 例) |
| `planner.json` | `eval/promptfoo.planner.yaml` | Planner 提示词回归(toolAccuracy scorer;被测对象是冻结提示词文本) |
| `persona.json` | `eval/promptfoo.persona.yaml` | 画像审计抽取质量(抽取成立性/scope 双层判定/置信档位路由) |
| `rag.json` | `eval/promptfoo.rag.yaml` | RAG 检索层直评(hit@k/段位/租户隔离/形状契约;全链无 LLM,零 token) |
| `data.json` | `eval/promptfoo.data.yaml` | 意图→闭集指标四要素映射(41 例;纯规则断言直调 resolve,零 LLM;评测集冻结为纯门永不入训) |
| `t1t2.json` | `eval/promptfoo.t1t2.yaml` | T1 组合/T2 探索双通道(LLM+闭集校验+AST 守卫链,ADR-0010 分层信任高风险面) |
| `latest.json` | — | 各套摘要的合并索引(不含逐用例明细);顶层时间戳=最后一次全量钉定 |

每个基线文件记录:结果摘要(pass/fail、各 scorer 聚合分)、逐用例通过明细、钉定时间、git SHA、
所用 yaml 的 sha256、**数据集指纹(testCases 文件清单+逐文件 sha256+合并哈希)**、promptfoo
版本——任何一项漂移都可追溯。数据集或 config 被改而基线未同批重钉,compare 直接判回归。

## 用法

```bash
# 首次钉定基线(任一基线已存在时拒绝执行,防无意漂移;可带套件名过滤,如 `-- rag data`)
bun run test:prompt:pin

# 现场重跑六套并与基线对比;任一回归即 exit 1
bun run test:prompt:compare

# 复用已有结果目录(文件名须为 unified.json / ... / t1t2.json,内容为 promptfoo -o 的 JSON 输出)
bun run test:prompt:compare -- --results-dir /path/to/results
```

⚠️ **解释器要求(2026-09-12)**:promptfoo 的 Python provider 落在系统默认 `python3` 上执行,
而 engine 依赖(redis/langgraph/sqlalchemy 等)不在系统环境 —— 缺依赖会以数十个
`Agent Provider execution error: No module named 'redis'` 形态假失败。对照/钉定必须带:

```bash
PROMPTFOO_PYTHON=$PWD/services/.venv/bin/python bun run test:prompt:compare
```

## 回归判定规则

以下任一情况判为回归,对比失败(exit 1):

- 用例总数、通过数下降,或失败数、错误数上升
- 整体均分或任一 scorer 聚合均分下降
- 基线中通过用例转为失败、或在本次结果中缺失
- 基线中的 scorer 在本次结果中消失
- **config 或数据集指纹变化**(2026-10-23:被改而基线未同批重钉,钉的就不再是当前行为)

## 数组 vars 律(2026-10-23,disableVarExpansion)

promptfoo `generateVarCombinations` 会把**数组值 vars 逐元素笛卡尔裂行** —— 
`expectedTools:[a,b]` 裂成两行、每行只断言**半个期望集**(unified 旧基线 58 行 vs 数据集
55 例即此产物;t1t2 角色闭集拒绝用例曾被裂成 4 行×四分之一闭集)。期望集必须整队断言:
unified/t1t2 配置已设 `defaultTest.options.disableVarExpansion: true`,新增配置沿用。
`expectedIntents` 走 JSON 串化是同坑的更早先例(aefb1e8)。

## python scorer 返回形状律(2026-10-23)

`{"pass", "score", "reason"}` 的 `reason` **必须 always-string** —— promptfoo
`isGradingResult` 对 `null` reason 整体拒收(assertions/python.js:66),成功路径回
`None` 会把通过误翻成「Python code execution failed」假红(data 册曾 38/42 假红于此)。

## 何时允许 --update 重新钉定

仅当**有意的提示词/引擎/数据集变更**经过评审接受后,在该行为变更的同一个 PR 中执行
`bun run test:prompt:pin -- --update` 并提交新基线。禁止为了"让对比通过"而静默重钉。
基线数字与数据集条数跨版本不可比时,PR 里写明(τ³-bench 式纪律)。

## classify 分册退役(2026-09-10)

`classify.json` 与 `promptfoo.classify.yaml` 已删除:其 7 个意图用例早已 1:1 收编进统一套件,且统一套件的意图用例自此经 agent_provider 真跑生产 triage 瀑布(此前 expectedIntents 直接回声,intentF1 恒 1.0 假绿)。分类回归由 unified 基线独立承担,独立分册纯属冗余。
