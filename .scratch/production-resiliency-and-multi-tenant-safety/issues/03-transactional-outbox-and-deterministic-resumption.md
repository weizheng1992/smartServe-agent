# 03 — 事务发件箱与确定性幂等恢复 (Transactional Outbox & Deterministic Idempotent Resumption)

**What to build:** 根除长事务审批恢复中的双写不一致与“幽灵工单”漏洞。在 `packages/db` 中创建 `approval_outbox_events` 表，在 `ApprovalGatekeeper` 中将工单决议（`approved` / `rejected`）与恢复事件记录在单个数据库本地事务中原子提交。调度派发采用确定性 Job ID（`job_resume_${approvalId}`）杜绝并发重试引起的重复执行；配套轻量级异步对账 Worker 定时补偿未完成事件，确保高危操作审批与恢复流绝对可靠。

**Blocked by:** None — can start immediately.

**Status:** closed

- [x] 数据库新建 `approval_outbox_events` 表（包含 `id`, `approvalId`, `threadId`, `eventType`, `payload`, `status`, `retryCount`, `createdAt`, `updatedAt`）
- [x] 重构 `ApprovalGatekeeper.processApprovalAction`，将工单状态更新与 Outbox 写入封装在单一 `db.transaction` 中
- [x] 实现确定性 Job ID 生成策略与防重放 Singleflight 锁，确保网络抖动重试不会导致重复退款
- [x] 实现 `ApprovalOutboxWorker` 对账补偿循环，周期性扫描 10 秒以上未处理完成的 Outbox 事件并自动拉起重试
- [x] 编写故障注入回归测试：模拟派发阶段网络抛错崩溃，验证对账 Worker 能够自动捕获并成功恢复任务，Outbox 状态最终迁移为 `completed`
