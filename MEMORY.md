# MEMORY.md —— 项目进度快照

更新于 2026-10-31。本文件记录「当前进行到哪」;稳定规则在 `AGENTS.md`,构建上下文在 `agent_docs/`。

## 主线定位

面试作品集主线:流可靠性 × 可评测(S1 断线恢复 → S2 打断 → S3 检索/评测)。叙事 C 级禁语清单见 `.scratch/portfolio-direction-verdict/`。

## 近期完成(2026-10 下旬)

- **judge v2 校准 94% 过线**(≥80% 达标,05 号票闭环),回填 changelog 2.26.1;v3 候选 = 多模态维度自判 N/A 豁免。
- **评测体系七缺口全收口**(2026-10-23 审计,末项 2026-10-28 收),五层金字塔第一梯队建成。
- **组合度量单源化**:metrics.yaml compose 块派生,组合度量不再双写(commit 5f7dba87 / f3c57520)。
- **夜评护栏加固**:launchd 产物存在性护栏(agent 空转零产物必重试);重试 + containment 已上线。
- **部署镜像瘦身**:linux 侧 torch 换 CPU 轮子,19.8GB → 约 12GB。
- **Data Agent 业界对齐裁决**:2026 共识 = Hybrid(语义层优先 + 守卫内自由生成兜底 + 歧义反问),本仓 T0/T1/T2 分层与赢家同构;P0 = 时间窗静默收窄修复 + 品类漂移修复 + 先遥测量化。

## 开放线程(待排期 / 待裁决)

- live-desk 后续:确认收货 B 级、web 面推卡、详情抽屉合并(P4 已完成 c950451,P5 退役项搁置)。
- 意图分析 Gen-3:一期纯收敛已落地验收,二~四期待排期。
- 删线程 FK 结构矛盾:threads 9 张 FK 子表 5 张 NOT NULL,「保审计 vs 删线程」待产品裁决(评测侧已兜底)。
- ADR-0011 归因增强边界:提议待裁决。
- Story 9(商品价格/库存编辑移交商户后台):案见 `.scratch/open-merchant-integration/issues/`。
- 夜间评测端口立约(NIGHTLY_BASE_URL=4001 约定已运行,正式立约待裁决)。
- Data Agent P0 三项(时间窗 / 品类漂移 / 遥测量化)待开工。

## 已知基建坑(高频复现,详见 `.claude/rules/` 与会话记忆)

gateway 热重载不监视 engine-py;并行会话 `uv sync` 会裁工作区依赖(恢复:`uv sync --package gateway-py --inexact`);testcontainers 扰动签名(InvalidPasswordError = 基建非代码,免 DB 子集秒绿即清白);pytest 在 Py3.14 退出阶段挂死(见 N passed 后 kill 即得完整结果);手拉网关必须带 `--env-file`。
