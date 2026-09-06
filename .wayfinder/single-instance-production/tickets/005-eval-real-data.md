---
id: "005"
title: evals 真数据入库
map: single-instance-production
type: ticket
labels: [wayfinder:task]
mode: AFK
assignee: ""
status: open
blocked-by: []
blocks: []
created: 2026-09-06
---

## Question

让 admin 评测页看到真实数据。现状:`gateway_py/routers/crud.py:342-364` 的 `/api/evals/*` 全部由本地随机生成器写 mock(响应显式 `isMock: True`);死表 `eval_runs`/`eval_results` 定义后无读写(`docs/agent-lifecycle-testing.md:244`);真实评测只走 promptfoo CLI 不入库。

**范围**(建图时已锁定的决策):

- **接通死表而非删表**:promptfoo 跑完后结果写入 `eval_runs`/`eval_results`(入库通道形态票内定:`test:prompt` 后挂导入步骤,或独立 CLI 脚本 `evals import`)。
- 随机生成器**降级为测试 fixture**:生产路由路径删除,pytest 里可复用。
- `apps/admin/src/pages/evals/` 页面去掉 isMock 标注,展示口径维持现状(展示形态演进在不建票范围,见地图 Not yet specified)。

**验收**:`bun run test:prompt` 后跑一次导入,admin 页显示真实运行记录且 `isMock` 消失;契约测试更新钉死新行为;`bun run test:eval` 不回归。
