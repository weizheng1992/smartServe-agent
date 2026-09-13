# 📋 Admin 控制平面可运营收尾规格书 (Operational Readiness Specification)

**状态:** Ready for Implementation (`ready-for-agent`)
**版本:** v1.0.0
**关联决策地图:** [.scratch/admin-console-readiness/map.md](../../.scratch/admin-console-readiness/map.md)(11 张决策工单全闭)

> 本规格由 wayfinder 地图收口。地图阶段已按各工单决策**完成实现并分簇提交**
> (`e3c14fa` → `a2444da` 共 5 个提交),本文件是这些决策与实现的规格化存档,
> 供后续回归、扩展与新会话理解现状;其中「实施决策」均为已落地事实。

---

## Problem Statement

SaaS 管理控制台(admin)作为平台运营者的唯一工作面,存在四类运营阻碍:

1. **决策不可归责**:HITL 审批(退款拦截、人工接管)的核准/驳回不记录操作者,审计链断裂;商户面与管理面各自有独立 resolve 通道,行为不一致。
2. **事实源分裂**:租户注册表(`tenants`)只含入驻商户,而平台业务数据散落在 ecommerce/nike/adidas/global 等未注册业务域——租户穿透、计费、画像归属、知识归属四处口径互不一致。
3. **指标不可信**:README 宣传「全局指标大盘」但产品中不存在该页面,宣传数字(94.2% Autopilot 率)系编造;会话列表/详情存在大量运行时假兜底值(850 tokens/$0.0035/假决策链/假运单号)。
4. **运营信息缺口**:评测批次无法下钻到逐用例样本;表单失败(API 4xx、校验失败)不可见;商户运营台未经系统化点击审计,存在资金审批卡金额显示 ¥0.00 的盲批风险。

## Solution

以「运营正确性优先」为序,对 admin 十一大模块做一次可运营收尾:

- 审批双通道(admin 面 + 商户面)统一注入核准人身份(actor/actorRole),随工单 payload 落库并在列表透出;
- 内置业务域以 `plan_tier='builtin'` 入租户注册表,配合禁删/禁停用保护,使全部消费面同源;
- 新增 `/dashboard` 全局大盘与单聚合端点,六张指标卡全部库内真算;
- 评测批次支持逐用例下钻;表单弹窗统一错误条;RAG 历史脏数据按知识文件 frontmatter 表驱动回填;
- 商户运营台完成七用例点击审计,审计抓获的缺陷(通道 actor 缺失、驳回原因被吞、审批卡金额缺失、徽标裸英文、浮动窗误挂)全部修复。

贯穿原则:**real-data-only** —— 运行时严禁编造值;数据缺失一律诚实空态(显式文案/0/-),失败必须可见。

## User Stories

1. As a 平台管理员, I want 每条审批决议记录核准人身份与角色, so that 事后可追责且合规审计有据可查。
2. As a 平台管理员, I want 审批列表直接显示驳回理由与核准人, so that 不必逐单打开 payload 深层 JSON 查找。
3. As a 平台管理员, I want 人工接管型工单在核准后显示「已接管完结」, so that 不会误以为仍待处理而重复决议。
4. As a 平台管理员, I want 未知审批状态以中性灰原文显示而非回落「待审批」, so that 新状态引入时不会误导运营。
5. As a 商户运营人员, I want 我在控制台的审批决议带商户操作员身份落库, so that 与平台管理面的决议可区分。
6. As a 商户运营人员, I want 我在驳回弹窗填写的原因原样落库, so that 顾客收到的拒绝说明与我填写的一致。
7. As a 商户运营人员, I want 退款审批卡显示订单真实金额, so that 不再盲批资金单。
8. As a 平台管理员, I want 内置业务域(ecommerce/nike/adidas/global)出现在租户注册表, so that 租户穿透、计费、画像、知识归属四处同源。
9. As a 平台管理员, I want 内置业务域禁删禁停用, so that nightly 评测与契约基线不会被一键破坏。
10. As a 平台管理员, I want 租户行显示「内置」徽标且不渲染删除按钮, so that 保护状态在界面上一目了然。
11. As a 平台管理员, I want 画像/知识录入弹窗的归属商户下拉来自注册表, so that 能为真实入驻商户录入数据。
12. As a 平台管理员, I want 一个全局大盘页, so that 打开控制台即可看到平台健康度而无需逐模块巡查。
13. As a 平台管理员, I want Autopilot 率由会话遥测真算, so that 我看到的解决率可对账可信。
14. As a 平台管理员, I want 待审批卡显示最老积压分钟数, so that 能感知审批积压并及时介入。
15. As a 平台管理员, I want 大盘含近 24h LLM 调用/成本/平均延迟, so that 掌握模型消耗趋势。
16. As a 平台管理员, I want 会话状态七态分布条, so that 一眼识别失败/熔断/降级的占比异常。
17. As a 平台管理员, I want 会话列表的 Token/成本/消息数为库内真算, so that 排查账单争议时有可信依据。
18. As a 平台管理员, I want 会话决策流 Tab 显示按节点聚合的真实 LLM 遥测(调用/Token/延迟/成本), so that 定位慢节点与异常调用有真实依据。
19. As a 平台管理员, I want 无遥测的会话显示诚实空态, so that 不会把快轨/规则路径误判为数据丢失。
20. As a 平台管理员, I want 侧栏底部显示网关真实探活状态, so that 网关宕机时立刻可见而非看到常绿的假状态灯。
21. As a 评测维护者, I want 点击评测批次行下钻逐用例结果, so that 失败样例可定位而非只见批次均值。
22. As a 评测维护者, I want 失败用例附错误信息红卡展示, so that 回归原因无需另行查库。
23. As a 评测维护者, I want 无样本数据的批次显示诚实空态, so that 不会被伪造的样本列表误导。
24. As a 内容运营者, I want 知识切片/画像表单提交失败时弹窗内出现红色错误条, so that 创建失败不再静默关窗丢数据。
25. As a 内容运营者, I want 知识切片的标题/分类由我填写并持久化, so that 知识库可按业务命名管理而非清一色兜底名。
26. As a 内容运营者, I want 知识分类筛选项与数据的真实分类 key 对齐, so that 筛选结果可用。
27. As a 平台管理员, I want 结单归档前出现二次确认, so that 不会误关正在服务的会话。
28. As a 平台管理员, I want 搜索/筛选变更自动回到第 1 页, so that 不会看到「有数据却显示空」的假空态。
29. As a 平台管理员, I want 审批动作详情列显示人读摘要(orderId/reason 等), so that 列表扫读不需要解析原始 JSON。
30. As a 商户运营人员, I want 顾客浮动客服窗不出现在运营台, so that 它不遮挡操作按钮且语义正确。
31. As a 商户运营人员, I want 订单状态徽标全部中文化, so that 列表阅读一致。
32. As a 平台开发者, I want 商品知识切片首行携带商品名, so that 品名相关的检索语义不再落空。
33. As a 平台开发者, I want RAG 历史行的标题按知识文件 frontmatter 表驱动回填, so that 知识库不再有兜底假名残留。
34. As a 平台管理员, I want 大盘/列表/详情所有数值可与 SQL 直接对账, so that 任何数字争议都能在库内验证。

## Implementation Decisions

### 审批核准人契约(工单 01,提交 `449b3e3`)

- resolve 请求体新增可选 `actor`(显示名)+ `actorRole` 枚举(`platform_admin | merchant_operator | system`);缺省由网关按调用面兜底:`x-role: admin` → platform_admin,其余 → merchant_operator;给了 actor 缺 role 按同一规则推断。
- 身份落 `actionPayload.resolvedBy/resolvedByRole`(与既有 humanReply/rejectionReason 同模式),**不做 schema 迁移**;非法 role 归 `system`。
- 存在两条 resolve 通道:`/api/approvals`(admin 面)与 `/api/admin/approvals`(商户面,网关 merchant 路由)——**两通道都必须注入**,商户面缺省 merchant_operator(审计抓获的漏点)。
- 引擎对 `human_escalation` 工单的 reject 语义是终态 `resolved_by_human`(结束接管);资金类(processRefund)reject 才是 `rejected`。
- 审批列表把 rejectionReason/humanReply/resolvedBy/resolvedByRole 从 payload 提到顶层供 UI 直接消费;admin「审批人」列优先真实核准人,历史无 actor 的接管型工单回落「人工坐席接管」;**历史数据不回填**。
- admin 显式传 `platform_admin`;商户面经 ui 包 `useApprovalMachine` 透传(新增 actor/actorRole 参数)。

### 租户注册表统一(工单 02)

- 方向:**live 种子补齐**(密封契约环境 conftest 的 SEED_TENANTS 与 `test_list_contains_seeded_tenants` 早已断言注册表应含内置域,漂移方是 live 种子)。
- engine seed 幂等插入四行:`ecommerce/nike/adidas/global`,`plan_tier='builtin'`;生产可用 `SEED_BUILTIN_TENANTS=false` 跳过。
- 保护:`DELETE /api/tenant/{id}` 对 builtin 403;`PUT` 对 builtin 拒停用(名称/行业可改);list 响应携带 `planTier`。
- 前端:租户 CRUD 行显示「内置」徽标且不渲染删除按钮;`lib/businessScopes.ts` 前端兜底**删除**(画像/知识归属下拉直连注册表)。

### 全局大盘(工单 03,决策+实现)

- 新路由 `/dashboard`,侧栏「业务运营」组第一项,默认落地页从 `/tenants` 改为 `/dashboard`。
- `GET /api/overview` 单聚合端点,一次请求出全部卡片;六卡:活跃租户数(近 7 天 session_metrics distinct business_id)、Autopilot 率(resolved_auto ÷ 总数)、待审批工单(waiting 计数 + 最老积压分钟)、Token/成本(session_metrics SUM,与计费页同源)、LLM 调用近 24h(llm_call_logs)、人工接管会话数(threads.assigned_operator_id 非空)。
- 会话状态七态分布条:resolved_auto / waiting_approval / failed / rejected / cancelled / llm_circuit_breaker / graph_error_degraded。
- 「在线客服坐席」**无在线状态数据源,诚实不做**,以人工接管会话数替代;README 宣传数字(94.2%)删除,改为真实口径描述,模块计数更新为 11。
- 30 秒自动刷新 + 手动刷新按钮。

### 评测下钻(工单 05 调研 → 10 落地)

- 关联键:`eval_run_records.id` 即 `eval_run_` 前缀 + `eval_runs.id`(导入器同事务写入);cases 端点按此前缀解析主键直查 `eval_results`。
- `GET /api/evals/results/{run_record_id}/cases` 返回逐用例 `caseName/passed/score/latencyMs/error`(metrics JSONB);解析失败/无样本诚实空。
- UI:评测行点击开 DetailDrawer,失败用例红卡附错误;二期(扩导入器带回复正文/断言明细)不在本期。

### 表单错误条(工单 08)

- `FormModal` 新增 `errorMessage` 插槽(顶部红条);五个表单弹窗(租户/画像/RAG/围栏/技能)接线 `useAdminCrud` 既有 `error` state(create/update 失败时写入并抛出,弹窗保持打开)。
- 字段级红字与 declarative 校验规则**延后**(现表单字段少,弹窗级足够;required 由原生气泡承担)。

### RAG 数据治理(工单 09,提交内含)

- 盘点口径:`metadata->>'title' IS NULL` / category 兜底值;结论:48 行无 title(全部来自合法知识文件与货架同步),**category 无脏数据**。
- 修复:知识文件行按 `docs/knowledge/*.md` frontmatter title 表驱动回填;货架同步行根因是同步器 chunk_text 首行缺商品名 → `build_product_chunks` 首行固定「商品名:{title}」并整组重灌(同步器幂等)。
- 防复发:网关建单携带用户 title/category(此前 `metadata=` 关键字遮蔽 SQLAlchemy 列属性 `metadata_` 的存量 bug 已修);「未分类」不进筛选下拉。

### real-data-only 去 mock(横切,`e3c14fa`)

- 会话列表 messageCount/totalTokens/costUsd 由网关 SQL LATERAL 聚合(messages/llm_call_logs 真算);假兜底(850/$0.0035/1 轮)退役。
- 会话决策流 Tab:编造假节点链(假耗时/置信度 0.985/假运单号/假免签阈值)整体退役,替换为 `GET /api/conversations/{threadId}/telemetry` 节点级真聚合 + 诚实空态。
- 侧栏底部 `/api/health` 真实探活(30s 轮询)替代硬编码「Engine v2.4 / 10 Nodes Active」。
- `_rag_item` 按商户编造文档名的兜底退役,诚实显示「未命名知识切片 (id 片段)」。
- 已知缺口(记录不在本期修):`llm_call_logs.node` 有 unknown 行,归因与修复口径见工单 06 Answer(7 个图外调用点补 bind + 嵌套 run 标注),待独立实施。

### 审计抓获的其他修复(`a2444da` 等)

- 搜索/筛选变更即重置页码(useAdminCrud 统一),消除「共 N 条,第 2/1 页」假空态。
- 审批动作列人读摘要(orderId/newAddress/reason/userInput 择要);结单归档二次确认;技能页筛选标签改「工具类型:」。
- 商户面:`useApprovalMachine` 驳回原因经 `explicitReason` 直传(修复 stale closure 吞原因);订单 DELIVERED 徽标中文化「已签收」;浮动客服窗路由排除 `/admin`。

## Testing Decisions

- **只测外部行为**:全部断言锚定 HTTP 契约形状与页面可见渲染,不测内部实现;数值类断言一律与直连 SQL 地面真值对账(如 overview 六卡、审批 actor 落库、会话遥测聚合)。
- **网关契约套件**(pytest,密封 testcontainers PG/Redis):本 effort 新增 9 条——RAG 建单标题落库/content 别名/空正文 422、检索诚实空与 all 视角、会话列表真遥测、遥测端点聚合与诚实空、actor 三分支(显式/兜底/非法)、商户通道 actor、builtin 保护(禁删/禁停用/改名放行)、overview 对账、租户 list 带 planTier。先例:`tests/test_http_routes_contract.py` 既有 TestRagDocuments/TestApprovals 模式。
- **Playwright e2e**(独立 Chromium):`apps/admin/e2e/fixRegression.e2e.ts`(修复回归 8 条)+ `deMockRegression.e2e.ts`(去 mock 3 条)+ `adminControlPlane.e2e.ts`(原冒烟 3 条),配置 `e2e/fix-regression.config.ts`(复用运行中的 3001/4000,不重播种);商户台 `apps/merchant/e2e/merchantConsoleAudit.e2e.ts`(审计 8 条,驳回流无 waiting 工单时数据驱动 skip),配置 `e2e/merchant-audit.config.ts`(baseURL 3005)。
- **方法学决定**:IAB 内嵌浏览器对本应用的注入点击/截图不可靠(工单 07 根因:宿主 guest surface 降级),GUI 测试一律走仓库 Playwright;CI 当前不跑 e2e,是否补三内核属另一决策。
- **数据治理类修复先盘点后动手**:只读 SQL 确认脏数据规模与口径(工单 09 实操:48 行 title 缺失、category 无脏),避免误「修」好数据。

## Out of Scope

- `apps/web` 客户端:扫描无 mock/缺陷,不入本 effort。
- 旧地图 `.scratch/wayfinder/`(商户自主入驻与配置中心)的 to-spec 回填:独立 effort。
- LLM 微调、多渠道 IM 网关物理接入:沿用旧地图 out-of-scope 结论。
- 审批 actor 的登录鉴权体系(admin 现无登录,本期记录「声明身份」;接入 SSO/JWT 后同一契约只换身份来源)。
- `llm_call_logs.node` unknown 行的存量回填(修复口径已在工单 06,只管增量)。
- 评测导入器二期(回复正文/断言明细入 metrics)。
- 字段级表单校验(红字+边框)与 declarative 校验规则。
- CI 补 e2e 步骤与 firefox/webkit 三内核保障。

## Further Notes

- **提交轨迹**(时间序):`e3c14fa`(9 项修复+去 mock)→ 工单 01 `449b3e3`(actor 契约)→ 工单 02(注册表统一)→ 工单 03(大盘)→ 工单 04/11(商户审计+三缺陷)→ 工单 10/08/09(下钻/错误条/数据治理)。
- **测试基线**:gateway pytest 130、engine pytest 615、admin bun test 35、admin e2e 14、merchant e2e 8(7 过 1 数据驱动 skip)。
- **并行会话注意**:仓库常有并行 WIP(如 step_execution_engine 在途改动含一个已知 F821),改 gatekeeper/merchant 路由前先 `git status` 确认;本规格的实现提交均与并行改动零交集。
- **截图证据**:审计过程截图(临时目录)已随收口删除;审计结论以工单 04/11 的文字记录为准。
- 商户台过滤语义:审批/会话按**线程归属租户**过滤(business_id 冗余不可信),造测试数据时必须先建正确归属的线程。
