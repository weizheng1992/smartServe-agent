---
id: "004"
title: HITL 审批流与熔断器 E2E 覆盖
map: single-instance-production
type: ticket
labels: [wayfinder:task]
mode: AFK
assignee: ""
status: open
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
