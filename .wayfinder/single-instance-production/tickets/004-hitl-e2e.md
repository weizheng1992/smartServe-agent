---
id: "004"
title: HITL 审批流与熔断器 E2E 覆盖
map: single-instance-production
type: ticket
labels: [wayfinder:task]
mode: AFK
assignee: "weizheng"
status: closed
blocked-by: ["001", "003"]
blocks: []
created: 2026-09-06
---

## Question

补齐 E2E 技术债:名为 HITL 的 `apps/web/e2e/chat-hitl.e2e.ts` 实际只测登录重定向与布局渲染,真正的 **HITL 审批挂起→人工核签→恢复执行** 流程与**熔断器** E2E 零覆盖(`docs/agent-lifecycle-testing.md:52` 挂账)。

**前置**:依赖 ticket 001(真实登录,E2E 不再靠 localStorage 兜底)与 ticket 003(熔断器存在才可测)。

**范围**:

- E2E:超阈值退款触发审批挂起 → web 端看到审批卡片 → 核签通过 → 会话恢复、卡片落定,全流程至少一条绿路径;熔断器 E2E 按可行形态取舍(可降为 mock LLM 失败注入后的前端可见状态)。
- 基建:补 `globalSetup` 种子(当前 E2E webServer 只拉前端,后端/DB 需手工就绪——至少把种子步骤脚本化)。

**验收**:`bun run test:e2e` 新用例绿且既有用例不回归;种子脚本可重复执行。

## Resolution

E2E 铺开后钉出并修复了三个执行层真缺陷,新用例两条绿路径落地;种子幂等可重复。收尾阶段按用户指示(本环境不再跑测试)以既有结果 + 静态检查收口。

### 钉出并修复的缺陷(3 个)

1. **HITL 挂起计划不落库的竞态**(engine):审批工单创建后对前端 2s 轮询立即可见,而挂起计划要等运行收口才 save_task_state —— 核签窗口内 `job_resume_*` 读到空计划,triage 误判查单,退款永不执行。修复:挂起即落库 + 空 thread_id 守卫(`584b1f8`)。新增回归 `test_suspension_persists_task_plan_immediately`。
2. **POST /api/chat/threads 契约缺失**(gateway):TS 基线从未实现,web「开启新一轮对话」fetch 404 被静默吞掉,按钮长期失效。补齐幂等建线程路由;评审追加归属守卫(同 id 异租户/异用户 409,不回显他人元数据;无主自愈认领)。**契约 39 → 40 条**(冻结 carve-out:新路由,不改既有线格式)。(`cc7a5d4`)
3. **tz-aware 送达日期炸退款 + 三方镜像表裸 except 连坐**(engine):text 列存 `NOW()` 带时区偏移,日期解析直接炸;镜像表更新失败但事务已中止,主退款 commit 静默失效、工具照报成功。修复:tz 归一 + 三处 `begin_nested` SAVEPOINT 隔离。(`584b1f8`)

### 新增 E2E 覆盖

- **HITL 审批流**(`chat-approval-flow.e2e.ts`):超阈值退款挂起 → 审批卡 → 核签 → 真实物理退款 → 会话落定。单独跑 **1 passed(19.7s)**。
- **LLM 熔断降级**(`circuit-breaker.e2e.ts`,独立 `playwright.breaker.config.ts`,死 LLM 注入 + 阈值 1):关键发现 —— 问候/订单/退款输入全走 triage 确定性旁路**零 LLM 调用**,熔断永不触发;价保咨询类输入必达 Step 3 精判,实测钉死「调用 1 失败 → OPEN → 调用 2 被拒 → 降级道歉」链路。单独跑 **1 passed(18.7s)**,并经手工探针验证 messages 落降级文案、session_metrics 落 `llm_circuit_breaker`。

### 基建

- `e2e/globalSetup.ts`:docker:up → db:push → db:seed 幂等就绪(种子改 DO UPDATE 重置 + 线程归属重绑,可重复执行 ✅)。
- webServer 显式数组化:gateway 4000 / web 3000 / admin 3001 / **merchant 3005**(基线靠 turbo 隐式拉起,数组化后必须显式保留)。
- `testIgnore` 围栏:breaker spec 独占运行 + `.claude/worktrees` 幽灵 spec 排除;`test:e2e` 改 `playwright test && playwright test -c playwright.breaker.config.ts`。
- admin 陈旧 spec 全量修缮(锚定当前文案/Combobox role=option/getByRole 防撞名);webkit + firefox 浏览器二进制补装。

### 验证台账(如实)

- 密封套件:gateway 契约 **91 passed**;engine 回放 **5 passed**(含新增挂起落库回归);ruff 双服务 clean;biome e2e clean。
- HITL/熔断两 spec 单独绿(见上)。
- **全量 `playwright test` 未在本环境收口**:修完已知根因后 25 passed / 18 failed —— 14 个为 firefox 二进制缺失(环境问题,已补装未复跑),4 个为 admin spec 选择器缺陷(已修:strict mode 撞名 + cmdk 选项非 `<label>`,修复基于组件源码静态核对,未复跑)。按用户指示本环境停止测试,修复待下次全量跑验证。
- `test:prompt:compare` 未跑:engine 改动仅 HITL 挂起路径,不触 Classify/Planner 提示词,基线设计上不受影响。

Commits:`584b1f8`(engine)、`cc7a5d4`(gateway)、`37833c1`(e2e)。
