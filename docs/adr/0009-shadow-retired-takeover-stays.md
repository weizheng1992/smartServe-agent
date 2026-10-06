# ADR-0009: shadow/ 影子双跑退役删除;takeover 业务逻辑迁包维持现状

- 日期: 2026-10-06
- 状态: 已决议(上一夜(2026-10-01)两项跨层重构候选的终局裁决,按推荐执行)
- 关联: TS 退役脉络(CLAUDE.md §2 后端历史)、ADR-0007(Temporal 路线退役)、`engine_py/approvals/takeover.py`

## 背景

2026-10-01 夜审提出两项跨层候选:①`engine_py/shadow/`(影子双跑与回放,207 行)在 TS 基线钉死后仅作回归参考,维护成本大于价值;②`takeover` 业务逻辑住 `engine_py/approvals/`,考虑迁包。

## 决策

### ① shadow/ 退役删除(采纳)

- **依据**:`git grep` 全仓零外部调用方(import 面),测试零覆盖;TS 侧 shadow 基线(1:1 移植期的逐字段 diff 与历史流量回放)在契约测试套件钉死 TS 行为后已完成历史使命(同 CLAUDE.md §2「行为由 pytest 契约测试钉死」的退役原则)。保留 = 207 行死代码 + 过时文档幻觉面。
- **执行**:删除 `engine_py/shadow/`(diff.py / replay.py / __init__.py);agent-engine.md §1.7 同步移除。
- **连带澄清**:仓内其余 "shadow" 字样与本案无关 —— `triage/semantic_routes.py` 的 `MODE_SHADOW`(语义路由灰度态:只产提议不接管路由)与 `analytics/l0_lexicon.py` / `metric_head` 的 shadow 模式(分类头并行打分只记日志)均为**活跃灰度机制**,语义同名不同物,不随本案退役。

### ② takeover 业务逻辑迁包:维持现状(否决)

- **依据**:takeover 逻辑现居 `engine_py/approvals/takeover.py`,与审批门禁(pending_approvals 真源、发件箱、暂停闸)同域强耦合 —— `_ctx`/chat/merchant/live_desk 四消费面全部经 `engine_py.approvals` 公共面消费,边界已经清晰。迁包收益(命名域洁癖)不抵牵动面(四消费面 + live-desk-rework 契约面联动)。
- **登记**:后续若 approvals 域再做结构性调整,可顺路重议;单独立项不做。

## 后果

- 全仓 "TS 退役残迹" 清零:pyproject/代码树不再含 1:1 移植期目录。
- 未来若需「新引擎 vs 冻结 TS 基线」的差分回放,以 pytest 契约测试为基线重建设施(重引入须新 ADR,同 ADR-0007 惯例)。
