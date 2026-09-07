---
id: "005"
title: evals 真数据入库
map: single-instance-production
type: ticket
labels: [wayfinder:task]
mode: AFK
assignee: "weizheng"
status: closed
blocked-by: []
blocks: []
created: 2026-09-06
resolved: 2026-09-07
---

## Question

让 admin 评测页看到真实数据。现状:`gateway_py/routers/crud.py:342-364` 的 `/api/evals/*` 全部由本地随机生成器写 mock(响应显式 `isMock: True`);死表 `eval_runs`/`eval_results` 定义后无读写(`docs/agent-lifecycle-testing.md:244`);真实评测只走 promptfoo CLI 不入库。

**范围**(建图时已锁定的决策):

- **接通死表而非删表**:promptfoo 跑完后结果写入 `eval_runs`/`eval_results`(入库通道形态票内定:`test:prompt` 后挂导入步骤,或独立 CLI 脚本 `evals import`)。
- 随机生成器**降级为测试 fixture**:生产路由路径删除,pytest 里可复用。
- `apps/admin/src/pages/evals/` 页面去掉 isMock 标注,展示口径维持现状(展示形态演进在不建票范围,见地图 Not yet specified)。

**验收**:`bun run test:prompt` 后跑一次导入,admin 页显示真实运行记录且 `isMock` 消失;契约测试更新钉死新行为;`bun run test:eval` 不回归。

## Resolution

**通道形态:两形态都给了。** 新增 `engine_py.evals.promptfoo_import`(CLI:`python -m engine_py.evals.promptfoo_import <json|目录>`);`bun run test:prompt:record` 链式跑三套件(unified/planner/classify → `eval/.records/`,已 gitignore)并自动调导入;`bun run evals:import` 为独立导入入口。导入单文件单事务写三表:`eval_runs`(UUID 主键 + git 提交号 + 通过率/scorer 均分/平均延迟/token 成本)、`eval_results`(逐用例行,metrics JSONB 含 score/latencyMs/error≤500)、`eval_run_records`(admin 展示汇总行,`/api/evals/results` 读该表)。JSON 形状兼容 0.111.x 外层 `{evalId, results: {results, stats}}` 与旧版根级两种(与 `eval/baselineLib.ts` 归一逻辑同义)。

**口径映射(DTO 冻结下的诚实映射)**:tool_accuracy←pass_rate;rag_faithfulness←scorer 均分;hitl_trigger_rate←0.0(套件不触达 HITL,诚实置零不造数);成本 tokens/1M×$0.15(observability §1.3 同口径,provider 不报 tokenUsage 时为真实 0)。business_id 固定 `platform`(套件为平台级回归,不归属单一租户)。

**随机生成器退役与降级**:`POST /api/evals/run` → 410(detail 指引 `test:prompt:record`);`/api/evals/results` 无 isMock、None 指标回退真实 0.0;随机播种逻辑降级为契约测试内 fixture `seed_random_eval_rows`(固定种子 20260907 可复现,列表测试消费);admin `api.ts` 移除无人消费的 `runEval` 绑定;`db/seed.py` 不再注入 eval-run-001/002/003 假行(dev 库已清理)。

**评审追补**(双轴评审 + 实跑发现):① CLI 缺 `__main__` 守卫 —— `python -m` 静默导入 exit 0,bun 链路首跑零入库零输出;补守卫 + 新增 CLI 入口回归测试(子进程实跑 + 断言行落库)。② `_git_commit` 空 except 补错误上下文 print。③ CLI 日志去 emoji 对齐 `[模块]` 先例。④ 测试内重复 `_fetch` 闭包提取为模块级 `_fetch_artifacts`。⑤ `docs/agent-lifecycle-testing.md` 前置清理行的 isMock 现在时表述补注退役时间线。

**记录的取舍(未改,有意保留)**:rag_faithfulness←通用 scorer 均分 vs admin 卡片"Contextual Retrieval 增益"文案存在语义松配 —— 票锁"展示口径维持现状",文案演进属地图 Not yet specified;`EvalRunRecordRow` 的 server_default(0.95/0.92/0.12)系 mock 时代残留,导入器恒写显式值不会触发,改默认值需 Alembic 迁移,记为已知债;每次 record 追加新行不去重(评测历史留痕,票未约定)。

**验证**:engine 150 passed(含 6 条新测)/ gateway sealed 88 passed / 双侧 ruff 干净;实跑 `test:prompt:record` 三套件 47+8+7 全绿,`eval_runs`×3(business=platform、git 提交号随行)、`eval_results`×62、`eval_run_records`×3 真实入库,admin `/api/evals/results` 数据源即为该表。提交 `d66a86f`。
