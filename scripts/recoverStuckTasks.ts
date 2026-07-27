import { db, getDrizzle } from 'db';
import { sql } from 'drizzle-orm';

async function recoverStuckTasks() {
  console.log('=====================================================');
  console.log('[Crash Recovery] 🛡️ Starting database audit for stuck tasks & expired approvals...');
  console.log('=====================================================');

  const drizzle = getDrizzle();
  if (!drizzle) {
    console.warn('[Crash Recovery] ⚠️ PostgreSQL is offline. Bypassing physical scan.');
    return;
  }

  const nowStr = new Date().toISOString();

  // =========================================================================
  // 1. Audit stuck & expired approvals (pending_approvals table)
  // =========================================================================
  try {
    console.log('[Crash Recovery] Scanning for expired approvals...');
    // Query pending approvals where status = 'waiting' and deadline is in the past
    const query = `
      SELECT id, thread_id AS "threadId", action_type AS "actionType", deadline
      FROM pending_approvals
      WHERE status = 'waiting' AND deadline < '${nowStr}'
    `;
    const res = await db.execute(query);
    const expiredApprovals = res.rows || [];

    if (expiredApprovals.length === 0) {
      console.log('[Crash Recovery] ✅ No expired pending approvals found.');
    } else {
      console.log(
        `[Crash Recovery] ⚠️ Detected [${expiredApprovals.length}] expired approvals. Transitioning states...`,
      );

      for (const approval of expiredApprovals as any[]) {
        const id = approval.id;
        const threadId = approval.threadId || approval.thread_id;
        const actionType = approval.actionType || approval.action_type;

        // Step A: Transition approval row to 'expired'
        await db.execute(`
          UPDATE pending_approvals
          SET status = 'expired'
          WHERE id = '${id}'
        `);
        console.log(`[Crash Recovery]   - Approval ID [${id}] for action [${actionType}] marked as EXPIRED.`);

        // Step B: Write a system message to the thread informing the customer
        const msgId = `msg_sys_exp_${Date.now()}_${Math.random().toString(36).substr(2, 5)}`;
        const messageContent = `【安全提示词】由于超过 30 分钟未获得管理员核准放行，当前申请退款的动作（${actionType}）已因超时被安全拦截挂起。如需继续办理，请重新发起对话申请。`;

        await db.addMessage({
          id: msgId,
          threadId: threadId,
          role: 'assistant',
          content: messageContent,
          timestamp: new Date().toISOString(),
        });
        console.log(`[Crash Recovery]   - Inserted automated timeout notification inside thread [${threadId}].`);
      }
    }
  } catch (err) {
    console.error('[Crash Recovery Error] Failed to scan or recover expired approvals:', err);
  }

  // =========================================================================
  // 2. Audit stuck session metrics resolutionStatus
  // =========================================================================
  try {
    console.log('\n[Crash Recovery] Scanning for stuck session metrics...');
    // Find sessions that have been in 'waiting_approval' status for over 2 hours
    const twoHoursAgo = new Date(Date.now() - 2 * 3600000).toISOString();

    const queryMetrics = `
      SELECT id, thread_id AS "threadId"
      FROM session_metrics
      WHERE resolution_status = 'waiting_approval' AND created_at < '${twoHoursAgo}'
    `;
    const resMetrics = await db.execute(queryMetrics);
    const stuckMetrics = resMetrics.rows || [];

    if (stuckMetrics.length === 0) {
      console.log('[Crash Recovery] ✅ No stuck session metrics found.');
    } else {
      console.log(
        `[Crash Recovery] ⚠️ Detected [${stuckMetrics.length}] stuck session metrics. Closing audited sessions...`,
      );

      for (const metric of stuckMetrics as any[]) {
        const metricId = metric.id;
        await db.execute(`
          UPDATE session_metrics
          SET resolution_status = 'expired'
          WHERE id = '${metricId}'
        `);
        console.log(
          `[Crash Recovery]   - Session Metric ID [${metricId}] updated from 'waiting_approval' -> 'expired'.`,
        );
      }
    }
  } catch (err) {
    console.error('[Crash Recovery Error] Failed to recover stuck session metrics:', err);
  }

  console.log('=====================================================');
  console.log('[Crash Recovery] ✅ Scan and self-healing recovery audit complete.');
  console.log('=====================================================');
}

// Execute scanning
recoverStuckTasks()
  .then(() => process.exit(0))
  .catch((err) => {
    console.error(err);
    process.exit(1);
  });
