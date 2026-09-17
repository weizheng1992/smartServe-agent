# 12: 重构 spec 汇编

Type: task
Status: resolved
Blocked by: 08, 09, 10, 11, 13, 14, 15, 16, 17, 18, 20

## Question

AFK 汇编：把全图决议组装成可交接 spec。**执行工具：调用 to-spec 技能**（其「无访谈纯综合、发布到 tracker、ready-for-agent」的形态与本票约束同构），源材料 = 各票 Answer 与地图 Decisions so far（不是只看当前对话）：

- 第①部分 模块边界：商城 agent ↔ data agent 缝清单与 interface 归属（引用 09）+ 商城侧最小收口项；
- 第②部分 data agent：技术路线全案（引用 08）+ SQL 安全链 + 首版能力清单与卡片（引用 10）+ 分阶段实现计划；
- 第③部分 模型策略：小模型决策文档（引用 11）+ 数据水龙头现状（引用 07）；
- 第④部分 后台系统模块规划：全局悬浮 agent + 模块化菜单（商品/分类/订单/用户/权限/运营）+ 实体对比 + 运营管理优惠活动（引用 19 修订、16、20）；
- 引用各票 Answer，不引入新决策；发现决议间冲突则回对应票文件追加 `## Comments` 提请重议，不自作主张裁决。
- **知识沉淀三件套（留以后用）**：① spec 正文按仓库惯例入 `docs/specs/`；② 完整地图 + 全部票据已随图活在 `docs/wayfinder/mall-data-agent-split/`（用户决议随 git 版本控制）——收尾时确认最终态一致即可；③ 08/09 号架构决议蒸馏成新 ADR 入 `docs/adr/`（沿用既有 ADR 编号惯例）。

完成即抵达目的地。


## Answer

决议日期 2026-09-18，spec 已汇编发布。

- **spec 正文**：`docs/specs/mall-data-agent-split.md`（Status: ready-for-agent；to-spec 模板：Problem/Solution/30 条 User Stories/六节 Implementation Decisions/Testing Decisions/Out of Scope/Further Notes 含六阶段实现排期）。
- **ADR-0004**：`docs/adr/0004-semantic-layer-route-and-dual-agent-seam.md`（08+09 两架构决议蒸馏，含否决项）。
- **知识沉淀三件套**：①spec 入 docs/specs/ ✅；②地图+票据活在 docs/wayfinder/mall-data-agent-split/（随 git）✅；③ADR ✅。
- 源材料 = 20 张票 Answer + 地图 Decisions（未只看对话）；汇编期间用户追加的两项（三层 RBAC 菜单/按钮配置粒度、顶栏快捷切换账号）已并入 spec 第 3 节并回写 13 号票 Comments。
- 冲突检查：未发现决议间冲突（10-D5「不做对比」与实体对比的表面冲突已由 10 号 Comments 修订消除——时间对比仍排除）。

**地图完成：20/20 票 resolved，目的地抵达。**
